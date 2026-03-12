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
    logging.warning("Unknown LOCALE '%s' — falling back to 'de'", os.getenv("LOCALE"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

from database import (init_db, get_unposted_article, mark_as_posted,
                      store_articles, get_polls_to_sync, apply_poll_delta, mark_poll_done)
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
    articles = scrape_new()
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
    mastodon_toot_id = None
    bluesky_url = None

    if os.getenv("MASTODON_ACCESS_TOKEN"):
        try:
            result = mastodon_client.post_question(article["question"], article["id"])
            mastodon_url = result["url"]
            mastodon_toot_id = result["toot_id"]
        except Exception:
            logger.exception("Mastodon post failed")

    if os.getenv("BLUESKY_APP_PASSWORD"):
        try:
            bluesky_url = bluesky_client.post_question(article["question"], article["id"])
        except Exception:
            logger.exception("Bluesky post failed")

    any_configured = bool(os.getenv("MASTODON_ACCESS_TOKEN") or os.getenv("BLUESKY_APP_PASSWORD"))
    any_succeeded  = bool(mastodon_url or bluesky_url)
    if not any_configured or any_succeeded:
        mark_as_posted(article["id"], mastodon_url=mastodon_url,
                       mastodon_toot_id=mastodon_toot_id, bluesky_url=bluesky_url)
        logger.info("Article %d marked as posted", article["id"])
    else:
        logger.error("All social posts failed — article %d NOT marked as posted", article["id"])


def sync_mastodon_polls():
    if not os.getenv("MASTODON_ACCESS_TOKEN"):
        return
    # Limit sync window to poll duration + 24h buffer so stuck polls
    # (missed expiry due to API errors) don't accumulate indefinitely.
    max_age = mastodon_client.POLL_DURATION // 3600 + 24
    polls = get_polls_to_sync(max_age_hours=max_age)
    for p in polls:
        try:
            counts = mastodon_client.sync_poll(p["toot_id"])
            if counts:
                apply_poll_delta(p["article_id"], counts["ja"], counts["nein"],
                                 p["poll_ja"], p["poll_nein"])
                if counts["expired"]:
                    mark_poll_done(p["article_id"])
                    logger.info("Poll for article %d expired — marked done", p["article_id"])
        except Exception:
            logger.exception("Poll sync failed for toot %s", p["toot_id"])


def main():
    init_db()
    seed_if_empty()
    logger.info("Bot started (interval: %d–%d minutes)", MIN_INTERVAL // 60, MAX_INTERVAL // 60)

    while True:
        try:
            run_cycle()
        except Exception:
            logger.exception("Error in bot cycle")
        try:
            sync_mastodon_polls()
        except Exception:
            logger.exception("Error syncing Mastodon polls")

        interval = random.randint(MIN_INTERVAL, MAX_INTERVAL)
        logger.info("Next post in %d minutes", interval // 60)
        time.sleep(interval)


if __name__ == "__main__":
    main()
