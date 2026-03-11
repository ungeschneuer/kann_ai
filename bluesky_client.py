import os
import logging
from pathlib import Path
from dotenv import load_dotenv
from atproto import Client
from utils import vote_cta

load_dotenv(os.getenv("DOTENV_PATH", str(Path(__file__).parent / ".env")))

logger = logging.getLogger(__name__)

# Singleton client — logs in once per process lifetime
_client: Client | None = None


def _get_client() -> Client:
    global _client
    if _client is None:
        handle = os.getenv("BLUESKY_HANDLE", "")
        password = os.getenv("BLUESKY_APP_PASSWORD", "")
        if not handle or not password:
            raise RuntimeError("BLUESKY_HANDLE or BLUESKY_APP_PASSWORD not set")
        _client = Client()
        _client.login(handle, password)
    return _client


def _post_url(at_uri: str) -> str:
    handle = os.getenv("BLUESKY_HANDLE", "")
    rkey = at_uri.split("/")[-1]
    return f"https://bsky.app/profile/{handle}/post/{rkey}"


def post_question(question: str, article_id: int) -> str:
    """Post a question to Bluesky and return the public post URL."""
    website_url = os.getenv("WEBSITE_URL", "http://localhost:8000")
    link = f"{website_url}/frage/{article_id}"
    text = f"{question}\n\n{vote_cta()} {link}"
    response = _get_client().send_post(text=text)
    url = _post_url(response.uri)
    logger.info("Posted to Bluesky: %s", url)
    return url
