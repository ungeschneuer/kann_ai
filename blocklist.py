"""
Blocklist of politically incorrect terms for DE and EN.
Used to filter articles during scraping and to clean up the database.
Matching is case-insensitive and checks word boundaries.
"""
import re

# German terms
_BLOCKED_DE = [
    "Indianer",
    "Indianerin",
    "Zigeuner",
    "Zigeunerin",
    "Neger",
    "Negerin",
    "Mohr",
    "Mohrin",
    "Eskimo",
    "Hottentotte",
    "Hottentottin",
    "Buschmann",
    "Buschleute",
    "Mulatte",
    "Mulattin",
    "Krüppel",
    "Schwachsinnige",
    "Schwachsinniger",
    "Schwachsinn",
    "Irrenhaus",
    "Geisteskranke",
    "Geisteskranker",
]

# English terms
_BLOCKED_EN = [
    "Gypsy",
    "Gypsies",
    "Negro",
    "Negroes",
    "Eskimo",
    "Eskimos",
    "Squaw",
    "Midget",
    "Cripple",
    "Cripples",
    "Retard",
    "Retarded",
    "Retards",
    "Spastic",
    "Lunatic",
    "Illegal Alien",
    "Illegal Aliens",
    "Tranny",
    "Trannies",
]

_PATTERNS_DE = [re.compile(rf"\b{re.escape(w)}\b", re.IGNORECASE) for w in _BLOCKED_DE]
_PATTERNS_EN = [re.compile(rf"\b{re.escape(w)}\b", re.IGNORECASE) for w in _BLOCKED_EN]


def is_blocked(text: str, locale: str = "de") -> bool:
    """Return True if the text contains a blocked term for the given locale."""
    patterns = _PATTERNS_EN if locale == "en" else _PATTERNS_DE
    return any(p.search(text) for p in patterns)
