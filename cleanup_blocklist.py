"""
Remove articles matching the blocklist or non-action title filter from the database.
Run with the correct DOTENV_PATH set:
  DOTENV_PATH=.env.de uv run python cleanup_blocklist.py
  DOTENV_PATH=.env.en uv run python cleanup_blocklist.py
"""
import sqlite3
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(os.getenv("DOTENV_PATH", str(Path(__file__).parent / ".env")))

from blocklist import is_blocked
from scraper import clean_title, _is_action_title

locale = os.getenv("LOCALE", "de")
db_path = os.getenv("DB_PATH", "kann_ai_de.db")


def _should_remove(title: str, question: str) -> bool:
    if is_blocked(title, locale) or is_blocked(question, locale):
        return True
    if not _is_action_title(clean_title(title)):
        return True
    return False


with sqlite3.connect(db_path) as conn:
    rows = conn.execute("SELECT id, title, question FROM articles").fetchall()
    ids = [r[0] for r in rows if _should_remove(r[1], r[2])]
    if ids:
        placeholders = ",".join("?" * len(ids))
        conn.execute(f"DELETE FROM articles WHERE id IN ({placeholders})", ids)
        conn.commit()
    print(f"Removed {len(ids)} of {len(rows)} articles from {db_path} (locale={locale})")
