import os
import logging
from pathlib import Path
from dotenv import load_dotenv
from mastodon import Mastodon
from utils import vote_cta

load_dotenv(os.getenv("DOTENV_PATH", str(Path(__file__).parent / ".env")))

logger = logging.getLogger(__name__)


def _client() -> Mastodon:
    return Mastodon(
        access_token=os.getenv("MASTODON_ACCESS_TOKEN"),
        api_base_url=os.getenv("MASTODON_INSTANCE_URL", "https://mastodon.social"),
    )


def _post_url(toot_id: str) -> str:
    handle = os.getenv("MASTODON_HANDLE", "")
    instance = os.getenv("MASTODON_INSTANCE_URL", "https://mastodon.social").rstrip("/")
    user = handle.split("@")[1] if handle.count("@") >= 2 else handle.lstrip("@")
    return f"{instance}/@{user}/{toot_id}"


def post_question(question: str, article_id: int) -> str:
    """Post a question to Mastodon, then reply with the vote link. Returns the public URL of the question post."""
    website_url = os.getenv("WEBSITE_URL", "http://localhost:8000")
    link = f"{website_url}/frage/{article_id}"
    client = _client()

    # First post: the question
    toot = client.toot(question)
    url = _post_url(str(toot["id"]))
    logger.info("Posted to Mastodon: %s", url)

    # Reply: vote CTA with link
    client.status_post(
        f"{vote_cta()} {link}",
        in_reply_to_id=toot["id"],
    )

    return url
