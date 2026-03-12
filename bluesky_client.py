import os
import logging
from pathlib import Path
from dotenv import load_dotenv
from atproto import Client, models
from utils import vote_cta
from web.og_image import generate_og_image

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


def _make_link_facet(text: str, link: str) -> list:
    """Return a facets list with a clickable link at the position of `link` in `text`."""
    text_bytes = text.encode("utf-8")
    link_bytes = link.encode("utf-8")
    start = text_bytes.rfind(link_bytes)
    if start == -1:
        return []
    return [
        models.AppBskyRichtextFacet.Main(
            features=[models.AppBskyRichtextFacet.Link(uri=link)],
            index=models.AppBskyRichtextFacet.ByteSlice(
                byte_start=start,
                byte_end=start + len(link_bytes),
            ),
        )
    ]


def post_question(question: str, article_id: int) -> str:
    """Post a question to Bluesky with the OG image and a link. Returns the public URL."""
    website_url = os.getenv("WEBSITE_URL", "http://localhost:8000")
    site_name = os.getenv("SITE_NAME", "Kann KI?")
    link = f"{website_url}/frage/{article_id}"
    post_text = f"{vote_cta()} {link}"

    png = generate_og_image(question, site_name, website_url)

    client = _get_client()
    post = client.send_image(
        text=post_text,
        image=png,
        image_alt=question,
        facets=_make_link_facet(post_text, link),
        langs=[LOCALE],
    )
    url = _post_url(post.uri)
    logger.info("Posted to Bluesky: %s", url)
    return url
