import os
import logging
from pathlib import Path
from dotenv import load_dotenv
from mastodon import Mastodon

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
    """Post a question to Mastodon with a native Yes/No poll. Returns {"url": str, "toot_id": str}."""
    from web.locales import de as _de, en as _en
    loc = (_en if LOCALE == "en" else _de).STRINGS

    client = _get_client()

    poll = client.make_poll(
        options=[loc["vote_yes_label"], loc["vote_no_label"]],
        expires_in=POLL_DURATION,
        multiple=False,
        hide_totals=False,
    )
    toot = client.status_post(
        question,
        poll=poll,
        language=LOCALE,
        visibility="public",
    )
    toot_id = str(toot["id"])
    url = _post_url(toot_id)
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
