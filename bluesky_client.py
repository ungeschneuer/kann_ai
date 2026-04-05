import os
import random
import logging
from pathlib import Path
from dotenv import load_dotenv
from atproto import Client
from web.og_image import generate_og_image, WINDOW_COLORS

load_dotenv(os.getenv("DOTENV_PATH", str(Path(__file__).parent / ".env")))

logger = logging.getLogger(__name__)
LOCALE = os.getenv("LOCALE", "de")

# Singleton client — logs in once per process lifetime
_client: Client | None = None


def _get_client() -> Client:
    global _client
    if _client is None:
        handle = os.getenv("BLUESKY_HANDLE", "")
        password = os.getenv("BLUESKY_APP_PASSWORD", "")
        if not handle or not password:
            raise RuntimeError("BLUESKY_HANDLE or BLUESKY_APP_PASSWORD not set")
        c = Client()
        c.login(handle, password)
        _client = c
    return _client


def _post_url(at_uri: str) -> str:
    handle = os.getenv("BLUESKY_HANDLE", "")
    rkey = at_uri.split("/")[-1]
    return f"https://bsky.app/profile/{handle}/post/{rkey}"


def post_question(question: str, article_id: int) -> str:
    """Post a question to Bluesky as either an image or plain text (50/50). Returns the public URL."""
    site_name = os.getenv("SITE_NAME", "Kann KI?")
    website_url = os.getenv("WEBSITE_URL", "http://localhost:8000")

    client = _get_client()

    if random.random() < 0.5:
        color = random.choice(WINDOW_COLORS)
        png = generate_og_image(question, site_name, website_url, window_color=color)
        post = client.send_image(
            text="",
            image=png,
            image_alt=question,
            langs=[LOCALE],
        )
    else:
        post = client.send_post(
            text=question,
            langs=[LOCALE],
        )

    url = _post_url(post.uri)
    logger.info("Posted to Bluesky: %s", url)
    return url
