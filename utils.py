import os


def vote_cta() -> str:
    """Return the localised call-to-action string for social media posts."""
    from web.locales import de as _de, en as _en
    locale = os.getenv("LOCALE", "de")
    return (_en if locale == "en" else _de).STRINGS["mastodon_vote_cta"]
