"""
Remove articles matching the blocklist from the database.
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

locale = os.getenv("LOCALE", "de")
db_path = os.getenv("DB_PATH", "kann_ai.db")

with sqlite3.connect(db_path) as conn:
    rows = conn.execute("SELECT id, title, question FROM articles").fetchall()
    ids = [r[0] for r in rows if is_blocked(r[1], locale) or is_blocked(r[2], locale)]
    if ids:
        placeholders = ",".join("?" * len(ids))
        conn.execute(f"DELETE FROM articles WHERE id IN ({placeholders})", ids)
        conn.commit()
    print(f"Removed {len(ids)} articles from {db_path} (locale={locale})")
