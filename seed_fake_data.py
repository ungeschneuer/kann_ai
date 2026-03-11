"""
Markiert zufaellige Artikel als gepostet und fuegt Fake-Stimmen hinzu.
Nur fuer lokales Testen – setzt voraus, dass die DB bereits Artikel enthaelt
(z.B. nach einem Scraping-Lauf).
Aufruf: uv run python seed_fake_data.py [anzahl]
"""
import os
import sys
import sqlite3
import uuid
import random
from datetime import datetime, timezone, timedelta
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(os.getenv("DOTENV_PATH", str(Path(__file__).parent / ".env")))

from database import DB_PATH, init_db

COUNT = int(sys.argv[1]) if len(sys.argv) > 1 else 30


def seed():
    init_db()
    now = datetime.now(timezone.utc)

    with sqlite3.connect(DB_PATH) as conn:
        total_available = conn.execute(
            "SELECT COUNT(*) FROM articles WHERE posted_at IS NULL"
        ).fetchone()[0]

        if total_available == 0:
            print("Keine ungeposteten Artikel in der DB. Zuerst scrapen.")
            return

        n = min(COUNT, total_available)
        rows = conn.execute(
            "SELECT id FROM articles WHERE posted_at IS NULL ORDER BY RANDOM() LIMIT ?", (n,)
        ).fetchall()
        article_ids = [r[0] for r in rows]

        for i, article_id in enumerate(article_ids):
            posted_at = (now - timedelta(days=n - i, hours=1)).isoformat()
            conn.execute(
                "UPDATE articles SET posted_at = ? WHERE id = ?",
                (posted_at, article_id),
            )

            total = random.randint(3, 80)
            ja_share = random.uniform(0.1, 0.9)
            for _ in range(total):
                vote = "ja" if random.random() < ja_share else "nein"
                voted_at = (now - timedelta(hours=random.randint(0, 720))).isoformat()
                try:
                    conn.execute(
                        "INSERT INTO votes (article_id, vote, voted_at, session_id) VALUES (?, ?, ?, ?)",
                        (article_id, vote, voted_at, str(uuid.uuid4())),
                    )
                except sqlite3.IntegrityError:
                    pass

        conn.commit()

        total_posted = conn.execute(
            "SELECT COUNT(*) FROM articles WHERE posted_at IS NOT NULL"
        ).fetchone()[0]
        total_votes = conn.execute("SELECT COUNT(*) FROM votes").fetchone()[0]

    print(f"Fertig: {n} Artikel als gepostet markiert ({total_posted} gesamt), {total_votes} Stimmen in {DB_PATH}")


if __name__ == "__main__":
    seed()
