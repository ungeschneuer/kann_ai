"""
WikiHow scraper. Reads configuration from environment variables.
Uses the sitemap as the article source; sub-sitemaps are fetched in parallel.

Articles are filtered by:
- Blocklist (blocklist.py): politically incorrect or offensive terms
- Non-action title filter: listicles, definitions, and other non-how-to patterns
  that would produce grammatically broken questions
"""
import os
import re
import asyncio
import logging
import httpx
from urllib.parse import unquote
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(os.getenv("DOTENV_PATH", str(Path(__file__).parent / ".env")))

from blocklist import is_blocked

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; KannAIBot/1.0)",
    "Accept-Language": "de-DE,de;q=0.9",
}

SITEMAP_URL     = os.getenv("WIKIHOW_SITEMAP_URL", "https://de.wikihow.com/sitemap.xml")
WIKIHOW_DOMAIN  = os.getenv("WIKIHOW_DOMAIN", "de.wikihow.com")
QUESTION_PREFIX = os.getenv("QUESTION_PREFIX", "Kann KI")
LOCALE          = os.getenv("LOCALE", "de")

# Words that should stay lowercase when they appear at the start of a question
LOWERCASE_STARTERS_DE = {
    "einen", "eine", "ein", "den", "die", "das", "der", "dem", "des",
    "sich", "mit", "zu", "in", "an", "auf", "aus", "von", "bei", "nach",
    "uber", "über", "unter", "vor", "hinter", "zwischen", "durch", "fur",
    "für", "ohne", "gegen", "um", "ab", "beim", "im", "am", "zum", "zur",
    "seinen", "seine", "ihren", "ihre", "ihr", "deinen", "deine", "dein",
    "meinen", "meine", "mein", "unseren", "unsere", "unser",
}

LOWERCASE_STARTERS_EN = {
    "a", "an", "the", "your", "his", "her", "their", "its", "our", "my",
    "someone", "something", "yourself", "themselves", "others",
}

LOWERCASE_STARTERS = LOWERCASE_STARTERS_EN if LOCALE == "en" else LOWERCASE_STARTERS_DE


def _slug_to_title(slug: str) -> str:
    title = unquote(slug)
    # Only strip wrapping quotes when both ends match (e.g. '"Foo"'), not one side
    for q in ('"', "'"):
        if title.startswith(q) and title.endswith(q) and len(title) > 2:
            title = title[1:-1]
            break
    title = title.strip()
    title = title.replace("-", " ")
    title = re.sub(r"\s+", " ", title).strip()
    return title


def clean_title(title: str) -> str:
    """Strip WikiHow-style prefixes like 'How to' or 'Wie man'."""
    if LOCALE == "en":
        title = re.sub(r"^How\s+to\s+", "", title, flags=re.IGNORECASE)
        title = re.sub(r"^How\s+do\s+you\s+", "", title, flags=re.IGNORECASE)
        title = re.sub(r"^How\s+can\s+I\s+", "", title, flags=re.IGNORECASE)
    else:
        title = re.sub(r"^Wie\s+man\s+", "", title, flags=re.IGNORECASE)
        title = re.sub(r"^Wie\s+du\s+", "", title, flags=re.IGNORECASE)
        title = re.sub(r"^So\s+(?=\w)", "", title, flags=re.IGNORECASE)
    return title.strip()


# Non-action prefixes that produce grammatically broken questions.
# These articles are typically listicles, definitions, or concept pages.
_BAD_PREFIXES_EN = re.compile(
    r"^\d|"  # starts with a number (e.g. "10 Signs...")
    r"^(What|Why|When|Where|Who|Which|Whether|"
    r"Signs|Symptoms|Reasons|Ways|Tips|Tricks|Facts|Types|"
    r"Understanding|Everything|Things|Examples|Differences|"
    r"Benefits|Effects|Causes|History|Overview|Introduction)\b",
    re.IGNORECASE,
)

_BAD_PREFIXES_DE = re.compile(
    r"^\d|"  # starts with a number
    r"^(Was|Warum|Wann|Wo|Wer|Welche|Welcher|Welches|"
    r"Zeichen|Symptome|Gründe|Wege|Tipps|Tricks|Fakten|Arten|Typen|"
    r"Unterschiede|Vorteile|Nachteile|Ursachen|Geschichte|Übersicht|"
    r"Alles|Dinge|Beispiele|Einführung)\b",
    re.IGNORECASE,
)


def _is_action_title(cleaned_title: str) -> bool:
    """Return True if the cleaned title looks like an actionable how-to."""
    pattern = _BAD_PREFIXES_EN if LOCALE == "en" else _BAD_PREFIXES_DE
    return not pattern.match(cleaned_title)


def make_question(title: str) -> str:
    """Turn an article title into a question, e.g. 'Kann KI Sushi zubereiten?'"""
    title = clean_title(title)
    words = title.split()
    if words and words[0].lower() in LOWERCASE_STARTERS:
        words[0] = words[0][0].lower() + words[0][1:]
    return QUESTION_PREFIX + " " + " ".join(words) + "?"


def _urls_to_articles(urls: list[str]) -> list[dict]:
    articles = []
    domain_escaped = re.escape(WIKIHOW_DOMAIN)
    for url in urls:
        match = re.search(rf"{domain_escaped}/(.+)$", url)
        if not match:
            continue
        slug = match.group(1)
        # Skip category pages and URLs with query strings or fragments
        if any(c in slug for c in (":", "?", "#")) or slug.startswith("Kategorie"):
            continue
        title = _slug_to_title(slug)
        if len(title) < 5:
            continue
        cleaned = clean_title(title)
        if not _is_action_title(cleaned):
            continue
        question = make_question(title)
        if is_blocked(title, LOCALE) or is_blocked(question, LOCALE):
            continue
        articles.append({
            "url": url,
            "title": title,
            "question": question,
        })
    return articles


async def _fetch_text(client: httpx.AsyncClient, url: str) -> str:
    try:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.text
    except httpx.HTTPError as e:
        logger.warning("Fetch error %s: %s", url, e)
        return ""


async def _async_fetch_all_urls() -> list[str]:
    """
    Fetch all article URLs from the WikiHow sitemap.
    Handles both flat sitemaps and sitemap index files.
    Sub-sitemaps are fetched in parallel, in batches of 10.
    """
    async with httpx.AsyncClient(headers=HEADERS, timeout=60) as client:
        root = await _fetch_text(client, SITEMAP_URL)
        if not root:
            return []
        logger.debug("Sitemap root preview: %s", root[:500])

        sub_urls = re.findall(r"<loc>([^<]+\.xml[^<]*)</loc>", root)
        if sub_urls:
            logger.info("Sitemap index: %d sub-sitemaps found", len(sub_urls))
            texts = []
            for i in range(0, len(sub_urls), 10):
                batch = sub_urls[i:i + 10]
                texts.extend(await asyncio.gather(*[_fetch_text(client, u) for u in batch]))
            combined = "\n".join(texts)
        else:
            combined = root

    locs = re.findall(r"<loc>([^<]+)</loc>", combined)
    locs = [u for u in locs if WIKIHOW_DOMAIN in u and not u.endswith(".xml")]
    logger.info("Sitemap: %d URLs found", len(locs))
    return locs


def fetch_all_urls() -> list[str]:
    return asyncio.run(_async_fetch_all_urls())


def scrape_all() -> list[dict]:
    """Return all articles from the WikiHow sitemap."""
    locs = fetch_all_urls()
    articles = _urls_to_articles(locs)
    logger.info("Prepared %d articles", len(articles))
    return articles


def scrape_new(known_urls: set[str]) -> list[dict]:
    """
    Return only articles whose URL is not already in known_urls.
    Efficient for regular cycles — only truly new articles are processed.
    """
    locs = fetch_all_urls()
    new_locs = [u for u in locs if u not in known_urls]
    logger.info("%d new URLs (out of %d total)", len(new_locs), len(locs))
    if not new_locs:
        return []
    articles = _urls_to_articles(new_locs)
    logger.info("Prepared %d new articles", len(articles))
    return articles
