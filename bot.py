"""
Bot process: scrapes WikiHow, posts questions to Mastodon and Bluesky.
Designed to run as a long-lived background process (e.g. via supervisord).
"""
import os
import time
import random
import logging
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(os.getenv("DOTENV_PATH", str(Path(__file__).parent / ".env")))

if os.getenv("LOCALE") not in ("de", "en"):
    import logging as _l
    _l.warning("Unknown LOCALE '%s' — falling back to 'de'", os.getenv("LOCALE"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

from database import init_db, get_unposted_article, get_known_urls, mark_as_posted, store_articles
from scraper import scrape_all, scrape_new
import mastodon_client
import bluesky_client

MIN_INTERVAL = int(os.getenv("BOT_MIN_INTERVAL", "30")) * 60
MAX_INTERVAL = int(os.getenv("BOT_MAX_INTERVAL", "120")) * 60


def seed_if_empty():
    """On first run, load the full WikiHow sitemap to build an article pool."""
    if get_unposted_article() is None:
        logger.info("No articles in database — loading full WikiHow sitemap")
        articles = scrape_all()
        added = store_articles(articles)
        logger.info("Added %d articles", added)


def run_cycle():
    """One bot cycle: check for new articles, then post one question."""
    known = get_known_urls()
    articles = scrape_new(known)
    if articles:
        added = store_articles(articles)
        if added:
            logger.info("Added %d new articles", added)

    article = get_unposted_article()
    if not article:
        logger.warning("No unposted article available")
        return

    logger.info("Posting: %s", article["question"])

    mastodon_url = None
    bluesky_url = None

    if os.getenv("MASTODON_ACCESS_TOKEN"):
        try:
            mastodon_url = mastodon_client.post_question(article["question"], article["id"])
        except Exception:
            logger.exception("Mastodon post failed")

    if os.getenv("BLUESKY_APP_PASSWORD"):
        try:
            bluesky_url = bluesky_client.post_question(article["question"], article["id"])
        except Exception:
            logger.exception("Bluesky post failed")

    mark_as_posted(article["id"], mastodon_url=mastodon_url, bluesky_url=bluesky_url)
    logger.info("Article %d marked as posted", article["id"])


def main():
    init_db()
    seed_if_empty()
    logger.info("Bot started (interval: %d–%d minutes)", MIN_INTERVAL // 60, MAX_INTERVAL // 60)

    while True:
        try:
            run_cycle()
        except Exception:
            logger.exception("Error in bot cycle")

        interval = random.randint(MIN_INTERVAL, MAX_INTERVAL)
        logger.info("Next post in %d minutes", interval // 60)
        time.sleep(interval)


if __name__ == "__main__":
    main()
