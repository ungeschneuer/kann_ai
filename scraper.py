"""
WikiHow scraper. Reads configuration from environment variables.
Uses the sitemap as the article source; sub-sitemaps are fetched concurrently
via a semaphore (no fixed batch size — slow responses don't block fast ones).

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
import spacy
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

# Compound adjective suffixes — spaCy's small DE model often tags these as NOUN.
# Used as a fallback when spaCy returns NOUN for the first token.
# Omitted: "haft" (-schaft nouns), "bar" (Minibar), "isch" (Tisch), "fest" (Stadtfest).
_DE_ADJ_SUFFIXES = (
    "arm", "reich", "los", "lich", "ig", "sam",
    "fähig", "würdig", "frei", "sicher", "mäßig", "voll",
)

# POS tags that indicate the first word should be lowercase
_LOWERCASE_POS = {"ADJ", "DET", "PRON", "ADP", "ADV", "VERB", "PART", "SCONJ", "CCONJ"}

# Lazy-loaded spaCy model (one per process)
_nlp: spacy.language.Language | None = None


def _get_nlp() -> spacy.language.Language:
    global _nlp
    if _nlp is None:
        model = "en_core_web_sm" if LOCALE == "en" else "de_core_news_sm"
        _nlp = spacy.load(model, disable=["ner", "parser"])
    return _nlp


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
    # Direct questions — produce "Can AI can/does/is/are..." constructions
    r"Can|Could|Should|Would|Will|Shall|"
    r"Does|Did|Do|Is|Are|Was|Were|Has|Have|Had|"
    # Indirect how-questions (not how-to actions)
    r"How\s+does|How\s+did|How\s+do\s+(?!you\b)|How\s+is|How\s+are|How\s+was|How\s+were|"
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
    r"Alles|Dinge|Beispiele|Einführung|"
    # Indirect question phrases (produce grammatically broken questions)
    r"In welche[mrns]?|Mit welche[mrns]?|Zu welche[mrns]?|"
    r"Für welche[mrns]?|Von welche[mrns]?|An welche[mrns]?|"
    r"Auf welche[mrns]?|Nach welche[mrns]?)\b",
    re.IGNORECASE,
)

_BAD_SUFFIXES_DE = re.compile(r"\b(Quiz|Test|Ratgeber|Checkliste|Übersicht)\s*$", re.IGNORECASE)
_BAD_SUFFIXES_EN = re.compile(r"\b(Quiz|Test|Checklist|Guide|Overview)\s*$", re.IGNORECASE)


def _is_action_title(cleaned_title: str) -> bool:
    """Return True if the cleaned title looks like an actionable how-to."""
    prefix_pattern = _BAD_PREFIXES_EN if LOCALE == "en" else _BAD_PREFIXES_DE
    suffix_pattern = _BAD_SUFFIXES_EN if LOCALE == "en" else _BAD_SUFFIXES_DE
    return not prefix_pattern.match(cleaned_title) and not suffix_pattern.search(cleaned_title)


def _make_question_from_doc(doc: spacy.tokens.Doc) -> str:
    """Build the question string from a pre-parsed spaCy doc."""
    tokens = list(doc)
    if not tokens:
        return QUESTION_PREFIX + "?"

    if LOCALE == "en":
        # English WikiHow uses title case. We run spaCy on the pre-lowercased input
        # (see make_question / _urls_to_articles) so common nouns are not mis-tagged
        # as PROPN due to capitalisation. Re-capitalise only genuine proper nouns.
        words = [t.text.capitalize() if t.pos_ == "PROPN" else t.text for t in tokens]
    else:
        words = [t.text for t in tokens]
        first_lower = words[0].lower()

        # Lowercase the first word if spaCy tags it as a non-noun POS.
        should_lower = tokens[0].pos_ in _LOWERCASE_POS
        # Fallback for compound adjectives (e.g. "ressourcenarm") — small model tags as NOUN.
        if not should_lower and any(first_lower.endswith(sfx) for sfx in _DE_ADJ_SUFFIXES):
            should_lower = True
        # Verb infinitive before a subordinating conjunction is unambiguously a verb
        # (e.g. "Erkennen ob …") — small model tags it NOUN in isolation.
        elif not should_lower and (
            len(tokens) > 1
            and tokens[1].pos_ == "SCONJ"
            and (first_lower.endswith("en") or first_lower.endswith("eln") or first_lower.endswith("ern"))
        ):
            should_lower = True

        if should_lower:
            words[0] = first_lower

        # Insert comma before subordinating conjunctions (German grammar requires it).
        result: list[str] = []
        for i, tok in enumerate(tokens):
            if i > 0 and tok.pos_ == "SCONJ" and not result[-1].endswith(","):
                result[-1] += ","
            result.append(words[i])
        words = result

    return QUESTION_PREFIX + " " + " ".join(words) + "?"


def make_question(title: str) -> str:
    """Turn a single article title into a question. Use _urls_to_articles for bulk."""
    cleaned = clean_title(title)
    if not cleaned:
        return QUESTION_PREFIX + "?"
    nlp_input = cleaned.lower() if LOCALE == "en" else cleaned
    return _make_question_from_doc(_get_nlp()(nlp_input))


def _urls_to_articles(urls: list[str]) -> list[dict]:
    """
    Convert sitemap URLs to article dicts.
    Filters without NLP first, then batch-processes all candidates through spaCy
    using nlp.pipe() — significantly faster than one call per article.
    """
    domain_escaped = re.escape(WIKIHOW_DOMAIN)
    candidates = []
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
        # Blocklist check on raw title (before NLP — cheap, no spaCy call)
        if is_blocked(title, LOCALE):
            continue
        candidates.append({"url": url, "title": title, "cleaned": cleaned})

    if not candidates:
        return []

    # Batch NLP: one pipeline pass over all candidate titles.
    # For English, lowercase first so title-case doesn't cause common nouns to be
    # mis-tagged as PROPN; _make_question_from_doc re-capitalises genuine proper nouns.
    nlp = _get_nlp()
    cleaned_titles = [c["cleaned"].lower() if LOCALE == "en" else c["cleaned"] for c in candidates]
    articles = []
    for candidate, doc in zip(candidates, nlp.pipe(cleaned_titles, batch_size=256)):
        question = _make_question_from_doc(doc)
        # Second blocklist check on the generated question (catches blocked terms
        # that only appear after question transformation)
        if not is_blocked(question, LOCALE):
            articles.append({
                "url":      candidate["url"],
                "title":    candidate["title"],
                "question": question,
            })
    return articles


async def _fetch_text(client: httpx.AsyncClient, url: str, *, retries: int = 3) -> str:
    """Fetch URL text with exponential backoff on transient errors."""
    for attempt in range(retries):
        try:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.text
        except httpx.HTTPError as e:
            if attempt == retries - 1:
                logger.warning("Fetch failed after %d attempts: %s (%s)", retries, url, e)
                return ""
            wait = 2 ** attempt
            logger.debug("Fetch attempt %d failed for %s, retrying in %ds", attempt + 1, url, wait)
            await asyncio.sleep(wait)
    return ""


async def _async_fetch_all_urls() -> list[str]:
    """
    Fetch all article URLs from the WikiHow sitemap.
    Handles both flat sitemaps and sitemap index files.
    Sub-sitemaps are fetched fully concurrently, limited to 10 simultaneous
    connections via a semaphore (no batch boundaries — slow responses don't
    block fast ones).
    """
    sem = asyncio.Semaphore(10)

    async def fetch_limited(client: httpx.AsyncClient, url: str) -> str:
        async with sem:
            return await _fetch_text(client, url)

    async with httpx.AsyncClient(headers=HEADERS, timeout=60) as client:
        root = await _fetch_text(client, SITEMAP_URL)
        if not root:
            return []
        logger.debug("Sitemap root preview: %s", root[:500])

        sub_urls = re.findall(r"<loc>([^<]+\.xml[^<]*)</loc>", root)
        if sub_urls:
            logger.info("Sitemap index: %d sub-sitemaps found", len(sub_urls))
            texts = await asyncio.gather(*[fetch_limited(client, u) for u in sub_urls])
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


def scrape_new() -> list[dict]:
    """
    Return only articles whose URL is not already in the database.
    Fetches the full sitemap but delegates deduplication to the DB layer
    (no full URL set loaded into Python memory).
    """
    from database import filter_new_urls
    locs = fetch_all_urls()
    new_locs = filter_new_urls(locs)
    logger.info("%d new URLs (out of %d total)", len(new_locs), len(locs))
    if not new_locs:
        return []
    articles = _urls_to_articles(new_locs)
    logger.info("Prepared %d new articles", len(articles))
    return articles
