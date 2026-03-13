"""
Regenerate the question field for all articles using the current scraper logic.
Run with: DOTENV_PATH=.env.de uv run python scripts/regenerate_questions.py
"""
import os
import sys
import sqlite3
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv(os.getenv("DOTENV_PATH", str(Path(__file__).parent.parent / ".env")))

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

from scraper import clean_title, _is_action_title, _get_nlp, _make_question_from_doc, LOCALE, QUESTION_PREFIX
from blocklist import is_blocked

DB_PATH = os.getenv("DB_PATH", "kann_ai_de.db")

def regenerate():
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("SELECT id, title FROM articles ORDER BY id").fetchall()
    logger.info("Regenerating questions for %d articles (locale=%s)", len(rows), LOCALE)

    nlp = _get_nlp()
    updated = 0
    deleted = 0

    ids_to_delete = []
    updates = []

    cleaned_list = []
    valid_rows = []
    for article_id, title in rows:
        cleaned = clean_title(title)
        if not _is_action_title(cleaned) or is_blocked(title, LOCALE):
            ids_to_delete.append(article_id)
            continue
        valid_rows.append((article_id, title))
        cleaned_list.append(cleaned.lower() if LOCALE == "en" else cleaned)

    for (article_id, title), doc in zip(valid_rows, nlp.pipe(cleaned_list, batch_size=256)):
        question = _make_question_from_doc(doc)
        if is_blocked(question, LOCALE):
            ids_to_delete.append(article_id)
            continue
        updates.append((question, article_id))

    if ids_to_delete:
        conn.executemany("DELETE FROM articles WHERE id=?", [(i,) for i in ids_to_delete])
        deleted = len(ids_to_delete)
        logger.info("Deleted %d articles (now filtered by current rules)", deleted)

    conn.executemany("UPDATE articles SET question=? WHERE id=?", updates)
    updated = len(updates)
    conn.commit()
    conn.close()
    logger.info("Updated %d questions, deleted %d articles", updated, deleted)

if __name__ == "__main__":
    regenerate()
