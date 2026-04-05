import io
import os
import random
import logging
from pathlib import Path
from dotenv import load_dotenv
from mastodon import Mastodon
from web.og_image import generate_og_image, WINDOW_COLORS

load_dotenv(os.getenv("DOTENV_PATH", str(Path(__file__).parent / ".env")))

logger = logging.getLogger(__name__)
LOCALE = os.getenv("LOCALE", "de")

_hours = os.getenv("MASTODON_POLL_DURATION_HOURS", "168")
POLL_DURATION = int(_hours) * 3600

_singleton: Mastodon | None = None


def _get_client() -> Mastodon:
    global _singleton
    if _singleton is None:
        _singleton = Mastodon(
            access_token=os.getenv("MASTODON_ACCESS_TOKEN"),
            api_base_url=os.getenv("MASTODON_INSTANCE_URL", "https://mastodon.social"),
        )
    return _singleton


def _post_url(toot_id: str) -> str:
    handle = os.getenv("MASTODON_HANDLE", "")
    instance = os.getenv("MASTODON_INSTANCE_URL", "https://mastodon.social").rstrip("/")
    user = handle.split("@")[1] if handle.count("@") >= 2 else handle.lstrip("@")
    return f"{instance}/@{user}/{toot_id}"


def post_question(question: str, article_id: int) -> dict:
    """Post a question to Mastodon as either an image or plain text (50/50). Returns {"url": str, "toot_id": str}."""
    site_name = os.getenv("SITE_NAME", "Kann KI?")
    website_url = os.getenv("WEBSITE_URL", "http://localhost:8000")

    client = _get_client()

    media_ids = None
    if random.random() < 0.5:
        color = random.choice(WINDOW_COLORS)
        png = generate_og_image(question, site_name, website_url, window_color=color)
        media = client.media_post(
            io.BytesIO(png),
            mime_type="image/png",
            description=question,
        )
        media_ids = [media]

    toot = client.status_post(
        question,
        media_ids=media_ids,
        language=LOCALE,
        visibility="public",
    )
    toot_id = str(toot["id"])
    url = toot.get("url") or _post_url(toot_id)
    logger.info("Posted to Mastodon: %s", url)
    return {"url": url, "toot_id": toot_id}


def sync_poll(toot_id: str) -> dict | None:
    """Fetch current poll vote counts for a toot.
    Returns {"ja": int, "nein": int, "expired": bool} or None if no poll."""
    global _singleton
    try:
        status = _get_client().status(toot_id)
    except Exception:
        _singleton = None  # force reconnect next call
        raise
    poll = status.get("poll")
    if not poll:
        return None
    options = poll["options"]  # [{"title": "Ja", "votes_count": N}, ...]
    return {
        "ja":      options[0]["votes_count"] or 0,
        "nein":    options[1]["votes_count"] or 0,
        "expired": bool(poll.get("expired")),
    }
