"""
Database layer for kann-ai-bot.
Synchronous functions are used by the bot; async functions by the web app.
"""
import sqlite3
import aiosqlite
import os
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(os.getenv("DOTENV_PATH", str(Path(__file__).parent / ".env")))

DB_PATH = os.getenv("DB_PATH", "kann_ai_de.db")

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

CREATE TABLE IF NOT EXISTS vote_counts (
    article_id  INTEGER PRIMARY KEY REFERENCES articles(id),
    ja          INTEGER NOT NULL DEFAULT 0,
    nein        INTEGER NOT NULL DEFAULT 0,
    total       INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS mastodon_posts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    article_id  INTEGER NOT NULL UNIQUE REFERENCES articles(id),
    toot_id     TEXT    NOT NULL,
    posted_at   TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS social_posts (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    article_id          INTEGER NOT NULL UNIQUE REFERENCES articles(id),
    mastodon_url        TEXT,
    mastodon_toot_id    TEXT,
    mastodon_poll_ja    INTEGER NOT NULL DEFAULT 0,
    mastodon_poll_nein  INTEGER NOT NULL DEFAULT 0,
    mastodon_poll_done  INTEGER NOT NULL DEFAULT 0,
    bluesky_url         TEXT,
    posted_at           TEXT    NOT NULL
);
"""


def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.executescript(SCHEMA)
        # One-time migration: fix old "Kann AI" typo (only runs if stale rows exist)
        if conn.execute("SELECT 1 FROM articles WHERE question LIKE 'Kann AI %' LIMIT 1").fetchone():
            conn.execute("UPDATE articles SET question = REPLACE(question, 'Kann AI ', 'Kann KI ')")
        # One-time migration: copy mastodon_posts into social_posts
        conn.execute("""
            INSERT OR IGNORE INTO social_posts (article_id, posted_at)
            SELECT article_id, posted_at FROM mastodon_posts
        """)
        # One-time migration: populate vote_counts from existing votes
        conn.execute("""
            INSERT OR IGNORE INTO vote_counts (article_id, ja, nein, total)
            SELECT
                article_id,
                SUM(CASE WHEN vote = 'ja'   THEN 1 ELSE 0 END),
                SUM(CASE WHEN vote = 'nein' THEN 1 ELSE 0 END),
                COUNT(*)
            FROM votes
            GROUP BY article_id
        """)
        # Migration: add new columns to social_posts if they don't exist yet
        for col, definition in [
            ("mastodon_toot_id",   "TEXT"),
            ("mastodon_poll_ja",   "INTEGER NOT NULL DEFAULT 0"),
            ("mastodon_poll_nein", "INTEGER NOT NULL DEFAULT 0"),
            ("mastodon_poll_done", "INTEGER NOT NULL DEFAULT 0"),
        ]:
            try:
                conn.execute(f"ALTER TABLE social_posts ADD COLUMN {col} {definition}")
            except sqlite3.OperationalError:
                pass  # column already exists
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


def filter_new_urls(urls: list[str]) -> list[str]:
    """
    Return only URLs from the list that are not already in the database.
    Uses a temporary table and a LEFT JOIN — avoids loading all DB URLs into memory.
    """
    if not urls:
        return []
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("CREATE TEMP TABLE _sitemap_check (url TEXT PRIMARY KEY)")
        conn.executemany("INSERT OR IGNORE INTO _sitemap_check (url) VALUES (?)", [(u,) for u in urls])
        rows = conn.execute(
            """SELECT c.url FROM _sitemap_check c
               LEFT JOIN articles a ON c.url = a.url
               WHERE a.url IS NULL"""
        ).fetchall()
    return [row[0] for row in rows]


def get_unposted_article() -> dict | None:
    """Return a random unposted article using an ID-range approach (avoids full table sort)."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """SELECT * FROM articles
               WHERE posted_at IS NULL
                 AND id >= (
                     SELECT MIN(id) + CAST(
                         (MAX(id) - MIN(id) + 1) * (ABS(RANDOM()) / 9223372036854775808.0)
                     AS INTEGER)
                     FROM articles WHERE posted_at IS NULL
                 )
               ORDER BY id LIMIT 1"""
        ).fetchone()
        # Fallback: ID-range can miss if the chosen ID is already posted — wrap around
        if row is None:
            row = conn.execute(
                "SELECT * FROM articles WHERE posted_at IS NULL ORDER BY id LIMIT 1"
            ).fetchone()
        return dict(row) if row else None


def mark_as_posted(article_id: int, mastodon_url: str | None = None,
                   mastodon_toot_id: str | None = None,
                   bluesky_url: str | None = None):
    """Mark an article as posted and store the social media URLs."""
    now = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "UPDATE articles SET posted_at = ? WHERE id = ?",
            (now, article_id),
        )
        conn.execute(
            """INSERT INTO social_posts (article_id, mastodon_url, mastodon_toot_id, bluesky_url, posted_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(article_id) DO UPDATE SET
                 mastodon_url     = COALESCE(excluded.mastodon_url,     mastodon_url),
                 mastodon_toot_id = COALESCE(excluded.mastodon_toot_id, mastodon_toot_id),
                 bluesky_url      = COALESCE(excluded.bluesky_url,      bluesky_url)""",
            (article_id, mastodon_url, mastodon_toot_id, bluesky_url, now),
        )
        conn.commit()


def get_polls_to_sync(max_age_hours: int = 192) -> list[dict]:
    """
    Return polls that are active and within the sync window.

    max_age_hours caps how far back to look (default: poll duration + 24h buffer).
    This prevents stuck polls (missed expiry due to API errors) from accumulating
    in the queue indefinitely as post count grows.
    """
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """SELECT article_id, mastodon_toot_id, mastodon_poll_ja, mastodon_poll_nein
               FROM social_posts
               WHERE mastodon_toot_id IS NOT NULL
                 AND mastodon_poll_done = 0
                 AND posted_at >= datetime('now', ? || ' hours')""",
            (f"-{max_age_hours}",),
        ).fetchall()
    return [
        {
            "article_id": row["article_id"],
            "toot_id":    row["mastodon_toot_id"],
            "poll_ja":    row["mastodon_poll_ja"],
            "poll_nein":  row["mastodon_poll_nein"],
        }
        for row in rows
    ]


def apply_poll_delta(article_id: int, new_ja: int, new_nein: int,
                     prev_ja: int, prev_nein: int):
    """Add the delta between new and previous poll counts to vote_counts."""
    delta_ja   = max(0, new_ja   - prev_ja)
    delta_nein = max(0, new_nein - prev_nein)
    if delta_ja == 0 and delta_nein == 0:
        return
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """INSERT INTO vote_counts (article_id, ja, nein, total)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(article_id) DO UPDATE SET
                 ja    = ja    + excluded.ja,
                 nein  = nein  + excluded.nein,
                 total = total + excluded.total""",
            (article_id, delta_ja, delta_nein, delta_ja + delta_nein),
        )
        conn.execute(
            """UPDATE social_posts SET mastodon_poll_ja = ?, mastodon_poll_nein = ?
               WHERE article_id = ?""",
            (new_ja, new_nein, article_id),
        )
        conn.commit()


def mark_poll_done(article_id: int):
    """Mark a poll as expired/finished so it is no longer included in sync queries."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "UPDATE social_posts SET mastodon_poll_done = 1 WHERE article_id = ?",
            (article_id,),
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
    """Return a random article with uniform distribution using a random offset into COUNT(*)."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM articles LIMIT 1 OFFSET (ABS(RANDOM()) % MAX(1, (SELECT COUNT(*) FROM articles)))"
        ) as cur:
            row = await cur.fetchone()
        return dict(row) if row else None


async def async_get_vote_counts(article_id: int) -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT ja, nein FROM vote_counts WHERE article_id = ?",
            (article_id,),
        ) as cur:
            row = await cur.fetchone()
    return {"ja": row[0], "nein": row[1]} if row else {"ja": 0, "nein": 0}


async def async_add_vote(article_id: int, vote: str, session_id: str) -> bool:
    """Store a vote and update the cached counts. Returns False if this session has already voted."""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT INTO votes (article_id, vote, voted_at, session_id) VALUES (?, ?, ?, ?)",
                (article_id, vote, datetime.now(timezone.utc).isoformat(), session_id),
            )
            ja_delta   = 1 if vote == "ja"   else 0
            nein_delta = 1 if vote == "nein" else 0
            await db.execute(
                """INSERT INTO vote_counts (article_id, ja, nein, total)
                   VALUES (?, ?, ?, 1)
                   ON CONFLICT(article_id) DO UPDATE SET
                     ja    = ja    + excluded.ja,
                     nein  = nein  + excluded.nein,
                     total = total + 1""",
                (article_id, ja_delta, nein_delta),
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
    """Return paginated questions with at least min_votes votes, using cached vote counts."""
    if sort not in SORT_OPTIONS:
        sort = "neu"
    col, direction = SORT_OPTIONS[sort]
    offset = (page - 1) * per_page

    query = f"""
        SELECT
            a.id,
            a.question,
            vc.total,
            vc.ja,
            vc.nein,
            ROUND(CAST(vc.ja   AS REAL) / vc.total * 100) AS ja_percent,
            ROUND(CAST(vc.nein AS REAL) / vc.total * 100) AS nein_percent,
            a.scraped_at
        FROM vote_counts vc
        JOIN articles a ON a.id = vc.article_id
        WHERE vc.total >= ?
        ORDER BY {col} {direction}
        LIMIT ? OFFSET ?
    """
    count_query = "SELECT COUNT(*) FROM vote_counts WHERE total >= ?"

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(count_query, (min_votes,)) as cur:
            total_count = (await cur.fetchone())[0]
        async with db.execute(query, (min_votes, per_page, offset)) as cur:
            rows = await cur.fetchall()

    result = []
    for row in rows:
        d = dict(row)
        d["total"]        = int(d["total"])
        d["ja"]           = int(d["ja"] or 0)
        d["nein"]         = int(d["nein"] or 0)
        d["ja_percent"]   = int(d["ja_percent"] or 0)
        d["nein_percent"] = int(d["nein_percent"] or 0)
        result.append(d)
    return result, total_count
