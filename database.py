"""
Database layer for kann-ai-bot.
Synchronous functions are used by the bot; async functions by the web app.
"""
import sqlite3
import aiosqlite
import os
from datetime import datetime, timezone

DB_PATH = os.getenv("DB_PATH", "kann_ai.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS articles (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    url         TEXT    UNIQUE NOT NULL,
    title       TEXT    NOT NULL,
    question    TEXT    NOT NULL,
    scraped_at  TEXT    NOT NULL,
    posted_at   TEXT
);

CREATE TABLE IF NOT EXISTS votes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    article_id  INTEGER NOT NULL REFERENCES articles(id),
    vote        TEXT    NOT NULL CHECK(vote IN ('ja', 'nein')),
    voted_at    TEXT    NOT NULL,
    session_id  TEXT    NOT NULL,
    UNIQUE(article_id, session_id)
);

CREATE TABLE IF NOT EXISTS mastodon_posts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    article_id  INTEGER NOT NULL UNIQUE REFERENCES articles(id),
    toot_id     TEXT    NOT NULL,
    posted_at   TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS social_posts (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    article_id   INTEGER NOT NULL UNIQUE REFERENCES articles(id),
    mastodon_url TEXT,
    bluesky_url  TEXT,
    posted_at    TEXT    NOT NULL
);
"""


def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.executescript(SCHEMA)
        # One-time migration: fix old "Kann AI" typo
        conn.execute("UPDATE articles SET question = REPLACE(question, 'Kann AI ', 'Kann KI ')")
        # One-time migration: copy mastodon_posts into social_posts
        conn.execute("""
            INSERT OR IGNORE INTO social_posts (article_id, posted_at)
            SELECT article_id, posted_at FROM mastodon_posts
        """)
        conn.commit()


# ---------------------------------------------------------------------------
# Synchronous functions (used by the bot)
# ---------------------------------------------------------------------------

def store_articles(articles: list[dict]) -> int:
    """Store scraped articles, skipping duplicates. Returns the number added."""
    now = datetime.now(timezone.utc).isoformat()
    added = 0
    with sqlite3.connect(DB_PATH) as conn:
        for article in articles:
            conn.execute(
                "INSERT OR IGNORE INTO articles (url, title, question, scraped_at) VALUES (?, ?, ?, ?)",
                (article["url"], article["title"], article["question"], now),
            )
            if conn.execute("SELECT changes()").fetchone()[0] > 0:
                added += 1
        conn.commit()
    return added


def get_known_urls() -> set[str]:
    """Return the set of all URLs already stored in the database."""
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute("SELECT url FROM articles").fetchall()
    return {row[0] for row in rows}


def get_unposted_article() -> dict | None:
    """Return a random article that has not been posted yet."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM articles WHERE posted_at IS NULL ORDER BY RANDOM() LIMIT 1"
        ).fetchone()
        return dict(row) if row else None


def mark_as_posted(article_id: int, mastodon_url: str | None = None,
                   bluesky_url: str | None = None):
    """Mark an article as posted and store the social media URLs."""
    now = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "UPDATE articles SET posted_at = ? WHERE id = ?",
            (now, article_id),
        )
        conn.execute(
            """INSERT INTO social_posts (article_id, mastodon_url, bluesky_url, posted_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(article_id) DO UPDATE SET
                 mastodon_url = COALESCE(excluded.mastodon_url, mastodon_url),
                 bluesky_url  = COALESCE(excluded.bluesky_url,  bluesky_url)""",
            (article_id, mastodon_url, bluesky_url, now),
        )
        conn.commit()


# ---------------------------------------------------------------------------
# Async functions (used by the web app)
# ---------------------------------------------------------------------------

async def async_get_article(article_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM articles WHERE id = ?", (article_id,)
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def async_get_random_article() -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM articles ORDER BY RANDOM() LIMIT 1"
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def async_get_vote_counts(article_id: int) -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT vote, COUNT(*) FROM votes WHERE article_id = ? GROUP BY vote",
            (article_id,),
        ) as cur:
            rows = await cur.fetchall()
    counts = {"ja": 0, "nein": 0}
    for vote, count in rows:
        counts[vote] = count
    return counts


async def async_add_vote(article_id: int, vote: str, session_id: str) -> bool:
    """Store a vote. Returns False if this session has already voted."""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT INTO votes (article_id, vote, voted_at, session_id) VALUES (?, ?, ?, ?)",
                (article_id, vote, datetime.now(timezone.utc).isoformat(), session_id),
            )
            await db.commit()
        return True
    except aiosqlite.IntegrityError:
        return False


async def async_get_user_vote(article_id: int, session_id: str) -> str | None:
    """Return the stored vote for a session, or None if not yet voted."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT vote FROM votes WHERE article_id = ? AND session_id = ?",
            (article_id, session_id),
        ) as cur:
            row = await cur.fetchone()
            return row[0] if row else None


async def async_get_social_posts(article_id: int) -> dict | None:
    """Return stored social media URLs for an article, or None."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT mastodon_url, bluesky_url FROM social_posts WHERE article_id = ?",
            (article_id,),
        ) as cur:
            row = await cur.fetchone()
            return {"mastodon_url": row[0], "bluesky_url": row[1]} if row else None


async def async_get_adjacent_articles(article_id: int) -> tuple[dict | None, dict | None]:
    """Return the previous and next articles by id."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT id, question FROM articles WHERE id < ? ORDER BY id DESC LIMIT 1",
            (article_id,),
        ) as cur:
            prev_row = await cur.fetchone()
        async with db.execute(
            "SELECT id, question FROM articles WHERE id > ? ORDER BY id ASC LIMIT 1",
            (article_id,),
        ) as cur:
            next_row = await cur.fetchone()
    return (dict(prev_row) if prev_row else None, dict(next_row) if next_row else None)


async def async_get_all_article_ids() -> list[tuple[int, str]]:
    """Return all article IDs with scraped_at timestamps, used for the sitemap."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT id, scraped_at FROM articles ORDER BY id"
        ) as cur:
            rows = await cur.fetchall()
    return [(row[0], row[1]) for row in rows]


SORT_OPTIONS = {
    "neu":        ("scraped_at",           "DESC"),
    "alt":        ("scraped_at",           "ASC"),
    "stimmen":    ("total",                "DESC"),
    "ja":         ("ja_percent",           "DESC"),
    "nein":       ("nein_percent",         "DESC"),
    "umstritten": ("ABS(ja_percent - 50)", "ASC"),
}


async def async_get_all_questions(
    min_votes: int = 3,
    sort: str = "neu",
    page: int = 1,
    per_page: int = 20,
) -> tuple[list[dict], int]:
    """Return paginated questions with at least min_votes votes."""
    if sort not in SORT_OPTIONS:
        sort = "neu"
    col, direction = SORT_OPTIONS[sort]
    offset = (page - 1) * per_page

    query = f"""
        SELECT id, question, total, ja, nein,
               CASE WHEN total > 0 THEN ROUND(CAST(ja   AS REAL) / total * 100) ELSE 0 END AS ja_percent,
               CASE WHEN total > 0 THEN ROUND(CAST(nein AS REAL) / total * 100) ELSE 0 END AS nein_percent
        FROM (
            SELECT
                a.id,
                a.question,
                a.scraped_at,
                COUNT(v.id)                                        AS total,
                SUM(CASE WHEN v.vote = 'ja'   THEN 1 ELSE 0 END)  AS ja,
                SUM(CASE WHEN v.vote = 'nein' THEN 1 ELSE 0 END)  AS nein
            FROM articles a
            LEFT JOIN votes v ON a.id = v.article_id
            GROUP BY a.id
            HAVING total >= ?
        )
        ORDER BY {col} {direction}
        LIMIT ? OFFSET ?
    """
    count_query = """
        SELECT COUNT(*) FROM (
            SELECT a.id, COUNT(v.id) AS total
            FROM articles a
            LEFT JOIN votes v ON a.id = v.article_id
            GROUP BY a.id
            HAVING total >= ?
        )
    """
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(count_query, (min_votes,)) as cur:
            total_count = (await cur.fetchone())[0]
        async with db.execute(query, (min_votes, per_page, offset)) as cur:
            rows = await cur.fetchall()

    result = []
    for row in rows:
        d = dict(row)
        d["total"]       = int(d["total"])
        d["ja"]          = int(d["ja"] or 0)
        d["nein"]        = int(d["nein"] or 0)
        d["ja_percent"]  = int(d["ja_percent"] or 0)
        d["nein_percent"] = int(d["nein_percent"] or 0)
        result.append(d)
    return result, total_count
