"""
Delete all posts from Mastodon and Bluesky for the configured account.

Usage:
    DOTENV_PATH=.env.de uv run python delete_all_posts.py
    DOTENV_PATH=.env.en uv run python delete_all_posts.py

Pass --dry-run to see what would be deleted without actually deleting.
"""
import os
import sys
import time
import logging
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(os.getenv("DOTENV_PATH", str(Path(__file__).parent / ".env")))
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

DRY_RUN = "--dry-run" in sys.argv


def delete_mastodon():
    token = os.getenv("MASTODON_ACCESS_TOKEN")
    base  = os.getenv("MASTODON_INSTANCE_URL", "https://mastodon.social")
    if not token:
        logger.info("MASTODON_ACCESS_TOKEN not set — skipping Mastodon")
        return

    from mastodon import Mastodon
    client = Mastodon(access_token=token, api_base_url=base)
    me = client.me()
    logger.info("Mastodon: logged in as %s", me["acct"])

    deleted = 0
    page = client.account_statuses(me["id"], limit=40)
    while page:
        for status in page:
            if DRY_RUN:
                logger.info("  [dry-run] would delete %s", status["url"])
            else:
                client.status_delete(status["id"])
                logger.info("  deleted %s", status["url"])
                deleted += 1
                time.sleep(0.3)   # stay well under rate limits
        page = client.fetch_next(page)

    logger.info("Mastodon: %s %d post(s)", "would delete" if DRY_RUN else "deleted", deleted)


def delete_bluesky():
    handle   = os.getenv("BLUESKY_HANDLE")
    password = os.getenv("BLUESKY_APP_PASSWORD")
    if not handle or not password:
        logger.info("BLUESKY_HANDLE / BLUESKY_APP_PASSWORD not set — skipping Bluesky")
        return

    from atproto import Client
    client = Client()
    client.login(handle, password)
    logger.info("Bluesky: logged in as %s", handle)

    deleted = 0
    cursor  = None
    while True:
        resp = client.get_author_feed(actor=handle, limit=50, cursor=cursor)
        items = resp.feed
        if not items:
            break
        for item in items:
            post = item.post
            # Only delete posts authored by this account (skip reposts)
            if post.author.handle != handle:
                continue
            if DRY_RUN:
                logger.info("  [dry-run] would delete %s", post.uri)
            else:
                client.delete_post(post.uri)
                logger.info("  deleted %s", post.uri)
                deleted += 1
                time.sleep(0.3)
        cursor = getattr(resp, "cursor", None)
        if not cursor:
            break

    logger.info("Bluesky: %s %d post(s)", "would delete" if DRY_RUN else "deleted", deleted)


if __name__ == "__main__":
    if DRY_RUN:
        logger.info("=== DRY RUN — nothing will be deleted ===")
    delete_mastodon()
    delete_bluesky()
    logger.info("Done.")
