"""
FastAPI-Web-App fuer kann-ai-bot.
"""
import os
import sys
import uuid
import asyncio
import logging
import hashlib
from contextlib import asynccontextmanager
from pathlib import Path
from collections import OrderedDict

from fastapi import FastAPI, Request, HTTPException, Form, Cookie, Query
from fastapi.responses import RedirectResponse, Response, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from dotenv import load_dotenv
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

load_dotenv(os.getenv("DOTENV_PATH", str(Path(__file__).parent.parent / ".env")))
sys.path.insert(0, str(Path(__file__).parent.parent))

from web.og_image import generate_og_image
from web.locales import de as _de_locale, en as _en_locale
from database import (
    init_db,
    async_get_article,
    async_get_random_article,
    async_get_vote_counts,
    async_add_vote,
    async_get_user_vote,
    async_get_social_posts,
    async_get_adjacent_articles,
    async_get_all_questions,
    async_get_all_article_ids,
    SORT_OPTIONS,
)

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent
LOCALE = os.getenv("LOCALE", "de")
if LOCALE not in ("de", "en"):
    logger.warning("Unbekannte LOCALE '%s' – verwende 'de'", LOCALE)
    LOCALE = "de"
LOC = (_en_locale if LOCALE == "en" else _de_locale).STRINGS
SITE_NAME = os.getenv("SITE_NAME", "Kann KI?")
WEBSITE_URL = os.getenv("WEBSITE_URL", "http://localhost:8000")
MASTODON_HANDLE = os.getenv("MASTODON_HANDLE", "")
_MASTODON_INSTANCE = os.getenv("MASTODON_INSTANCE_URL", "https://mastodon.social").rstrip("/")
_handle_user = MASTODON_HANDLE.split("@")[1] if MASTODON_HANDLE.count("@") >= 2 else MASTODON_HANDLE.lstrip("@")
MASTODON_URL = f"{_MASTODON_INSTANCE}/@{_handle_user}" if _handle_user else ""

BLUESKY_HANDLE = os.getenv("BLUESKY_HANDLE", "")
BLUESKY_URL = f"https://bsky.app/profile/{BLUESKY_HANDLE}" if BLUESKY_HANDLE else ""

OTHER_LOCALE_URL = os.getenv("OTHER_LOCALE_URL", "")


def _static_version() -> str:
    h = hashlib.md5()
    static = BASE_DIR / "static"
    if static.is_dir():
        for f in sorted(static.rglob("*.css")) + sorted(static.rglob("*.js")):
            h.update(f.read_bytes())
    return h.hexdigest()[:8]

STATIC_VERSION = _static_version()

limiter = Limiter(key_func=get_remote_address)

# OG-Image-Cache mit Groessenbegrenzung: article_id -> (etag, png_bytes)
_OG_CACHE_MAX = 500
_og_cache: OrderedDict[int, tuple[str, bytes]] = OrderedDict()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(docs_url=None, redoc_url=None, lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------

def _session(session_id: str | None) -> str:
    return session_id or str(uuid.uuid4())


def _base_ctx(request: Request) -> dict:
    return {
        "request": request,
        "site_name": SITE_NAME,
        "sv": STATIC_VERSION,
        "mastodon_handle": MASTODON_HANDLE,
        "mastodon_url": MASTODON_URL,
        "bluesky_handle": BLUESKY_HANDLE,
        "bluesky_url": BLUESKY_URL,
        "website_url": WEBSITE_URL,
        "other_locale_url": OTHER_LOCALE_URL,
        "loc": LOC,
    }


# ---------------------------------------------------------------------------
# Routen
# ---------------------------------------------------------------------------

_home_og_cache: tuple[str, bytes] | None = None


@app.get("/preview.png")
async def home_og_preview(request: Request):
    global _home_og_cache
    etag = hashlib.md5(LOC["home_tagline"].encode()).hexdigest()
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304)
    if not _home_og_cache or _home_og_cache[0] != etag:
        loop = asyncio.get_running_loop()
        png = await loop.run_in_executor(
            None,
            lambda: generate_og_image(LOC["home_tagline"], SITE_NAME, {}, WEBSITE_URL),
        )
        _home_og_cache = (etag, png)
    return Response(content=_home_og_cache[1], media_type="image/png", headers={
        "Cache-Control": "public, max-age=86400",
        "ETag": etag,
    })


@app.get("/")
async def index(request: Request):
    return templates.TemplateResponse("home.html", {
        **_base_ctx(request),
        "og_image_url": f"{WEBSITE_URL}/preview.png",
    })


@app.get("/zufall")
async def random_question(request: Request, session_id: str | None = Cookie(default=None)):
    article = await async_get_random_article()
    if not article:
        return templates.TemplateResponse("empty.html", _base_ctx(request), status_code=200)
    resp = RedirectResponse(url=f"/frage/{article['id']}", status_code=302)
    if not session_id:
        resp.set_cookie("session_id", str(uuid.uuid4()), max_age=365 * 24 * 3600,
                        httponly=True, samesite="lax")
    return resp


@app.get("/frage/{article_id}")
async def question_page(
    article_id: int,
    request: Request,
    session_id: str | None = Cookie(default=None),
):
    article = await async_get_article(article_id)
    if not article:
        raise HTTPException(status_code=404, detail="Frage nicht gefunden")

    session = _session(session_id)
    counts = await async_get_vote_counts(article_id)
    prev_a, next_a = await async_get_adjacent_articles(article_id)
    social = await async_get_social_posts(article_id)

    total = counts["ja"] + counts["nein"]
    ja_pct = round(counts["ja"] / total * 100) if total else 0
    nein_pct = 100 - ja_pct if total else 0

    user_voted = request.cookies.get(f"voted_{article_id}")
    article_url = f"{WEBSITE_URL}/frage/{article_id}"
    og_image_url = f"{WEBSITE_URL}/frage/{article_id}/preview.png"

    ctx = {
        **_base_ctx(request),
        "article": article,
        "counts": counts,
        "total": total,
        "ja_pct": ja_pct,
        "nein_pct": nein_pct,
        "user_voted": user_voted,
        "prev_article": prev_a,
        "next_article": next_a,
        "article_url": article_url,
        "og_image_url": og_image_url,
        "social": social,
    }
    resp = templates.TemplateResponse("question.html", ctx)
    resp.set_cookie("session_id", session, max_age=365 * 24 * 3600,
                    httponly=True, samesite="lax")
    return resp


_BOT_UA_PATTERNS = (
    "bot", "crawler", "spider", "curl", "wget", "python-httpx",
    "python-requests", "go-http", "scrapy", "libwww", "okhttp",
)

def _is_bot(request: Request) -> bool:
    ua = request.headers.get("user-agent", "").lower()
    if not ua:
        return True
    return any(p in ua for p in _BOT_UA_PATTERNS)


@app.post("/frage/{article_id}/abstimmen")
@limiter.limit("5/minute")
async def vote(
    request: Request,
    article_id: int,
    vote: str = Form(...),
    session_id: str | None = Cookie(default=None),
):
    if _is_bot(request):
        raise HTTPException(status_code=403, detail="Automatisierte Anfragen nicht erlaubt")

    if vote not in ("ja", "nein"):
        raise HTTPException(status_code=400, detail="Ungueltige Stimme")

    article = await async_get_article(article_id)
    if not article:
        raise HTTPException(status_code=404, detail="Frage nicht gefunden")

    session = _session(session_id)
    accepted = await async_add_vote(article_id, vote, session)

    # If vote was rejected (duplicate session), retrieve the stored vote so the
    # cookie and results view reflect what was actually counted.
    if not accepted:
        stored = await async_get_user_vote(article_id, session)
        if stored:
            vote = stored

    resp = RedirectResponse(url=f"/frage/{article_id}", status_code=303)
    resp.set_cookie("session_id", session, max_age=365 * 24 * 3600,
                    httponly=True, samesite="lax")
    resp.set_cookie(f"voted_{article_id}", vote, max_age=365 * 24 * 3600,
                    httponly=True, samesite="lax")
    return resp


@app.get("/frage/{article_id}/preview.png")
async def og_preview(article_id: int, request: Request):
    article = await async_get_article(article_id)
    if not article:
        raise HTTPException(status_code=404)

    etag = hashlib.md5(article["question"].encode()).hexdigest()

    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304)

    cached = _og_cache.get(article_id)
    if cached and cached[0] == etag:
        png = cached[1]
    else:
        loop = asyncio.get_running_loop()
        png = await loop.run_in_executor(
            None,
            lambda: generate_og_image(article["question"], SITE_NAME, {}, WEBSITE_URL),
        )
        if len(_og_cache) >= _OG_CACHE_MAX:
            _og_cache.popitem(last=False)
        _og_cache[article_id] = (etag, png)

    return Response(content=png, media_type="image/png", headers={
        "Cache-Control": "public, max-age=86400",
        "ETag": etag,
    })


PER_PAGE = 20

SORT_LABELS = {
    "neu":        LOC["sort_new"],
    "alt":        LOC["sort_old"],
    "stimmen":    LOC["sort_votes"],
    "ja":         LOC["sort_yes"],
    "nein":       LOC["sort_no"],
    "umstritten": LOC["sort_controversial"],
}

@app.get("/alle")
async def all_questions(
    request: Request,
    sort: str = Query(default="neu"),
    seite: int = Query(default=1, ge=1),
):
    if sort not in SORT_LABELS:
        sort = "neu"
    questions, total_count = await async_get_all_questions(
        min_votes=3, sort=sort, page=seite, per_page=PER_PAGE
    )
    total_pages = max(1, -(-total_count // PER_PAGE))
    return templates.TemplateResponse("all_questions.html", {
        **_base_ctx(request),
        "questions": questions,
        "sort": sort,
        "sort_labels": SORT_LABELS,
        "page": seite,
        "total_pages": total_pages,
        "total_count": total_count,
    })


@app.get("/about")
async def about(request: Request):
    return templates.TemplateResponse("about.html", _base_ctx(request))


@app.get("/robots.txt", response_class=PlainTextResponse)
async def robots():
    return f"User-agent: *\nAllow: /\nSitemap: {WEBSITE_URL}/sitemap.xml\n"


@app.get("/sitemap.xml")
async def sitemap():
    article_ids = await async_get_all_article_ids()
    static_pages = ["", "/alle", "/about"]
    urls = "\n".join(
        f"  <url><loc>{WEBSITE_URL}{path}</loc></url>"
        for path in static_pages
    )
    urls += "\n" + "\n".join(
        f"  <url><loc>{WEBSITE_URL}/frage/{aid}</loc>"
        f"<lastmod>{scraped_at[:10]}</lastmod></url>"
        for aid, scraped_at in article_ids
    )
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
{urls}
</urlset>"""
    return Response(content=xml, media_type="application/xml")
