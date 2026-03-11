import os
import logging
from pathlib import Path
from dotenv import load_dotenv
from atproto import Client, models
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


def _make_link_facet(text: str, link: str) -> list:
    """Return a facets list with a clickable link at the position of `link` in `text`."""
    text_bytes = text.encode("utf-8")
    link_bytes = link.encode("utf-8")
    start = text_bytes.rfind(link_bytes)
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
    """Post a question to Bluesky, then reply with the vote link. Returns the public URL of the question post."""
    website_url = os.getenv("WEBSITE_URL", "http://localhost:8000")
    link = f"{website_url}/frage/{article_id}"
    client = _get_client()

    # First post: the question
    first = client.send_post(text=question)
    url = _post_url(first.uri)
    logger.info("Posted to Bluesky: %s", url)

    # Reply: vote CTA with clickable link
    reply_text = f"{vote_cta()} {link}"
    reply_ref = models.AppBskyFeedPost.ReplyRef(
        root=models.create_strong_ref(first),
        parent=models.create_strong_ref(first),
    )
    client.send_post(
        text=reply_text,
        reply_to=reply_ref,
        facets=_make_link_facet(reply_text, link),
    )

    return url
