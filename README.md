# Can AI do it? / Kann KI das?

A bilingual voting bot and web app. It scrapes WikiHow articles, turns their titles
into yes/no questions ("Can AI bake a soufflé?"), posts them to Mastodon and Bluesky,
and lets visitors vote on the result.

Two instances run from the same codebase — one in German, one in English — each with
its own database, social accounts, and domain.

Live: [kann-ki.schneuer.online](https://kann-ki.schneuer.online) (DE) /
[can-ai.schneuer.online](https://can-ai.schneuer.online) (EN)

## How it works

A bot runs in the background on a randomised interval (default 30–120 min). Each cycle:

1. Fetches the WikiHow sitemap and stores any new articles
2. Picks one unposted article at random
3. Posts the question to Mastodon and/or Bluesky — the question as the main post, the vote link as a reply
4. Marks the article as posted so it is never repeated

The web app is independent — it shows all scraped articles regardless of posting status.
Visitors vote yes or no; results appear once a question reaches 3 votes.

### Content filtering

The scraper filters out articles that do not produce well-formed questions:

- **Blocklist** (`blocklist.py`): politically incorrect or offensive terms in both DE and EN
- **Non-action titles**: listicles ("10 Signs..."), definitions ("What is..."), and other
  non-how-to article types that generate grammatically broken questions

Run `cleanup_blocklist.py` after updating the blocklist to remove existing database entries.

## Stack

- **Python 3.11+**, managed by [uv](https://github.com/astral-sh/uv)
- **FastAPI** + **uvicorn** for the web app
- **SQLite** via aiosqlite (async web app) and sqlite3 (bot)
- **Jinja2** templates with a retro TUI aesthetic ([TuiCss](https://github.com/vinibiavatti1/TuiCss))
- **Pillow** for generating Open Graph preview images
- **mastodon.py** and **atproto** for social posting
- **slowapi** for rate limiting on the vote endpoint

## Setup

### Requirements

- Python 3.11+
- [uv](https://github.com/astral-sh/uv)

### Install

```bash
git clone https://github.com/yourname/kann_ai_bot
cd kann_ai_bot
uv sync
```

### Configure

```bash
cp .env.example .env
# edit .env with your credentials
```

| Variable | Description |
|---|---|
| `LOCALE` | `de` or `en` — controls language, question format, and scraper behaviour |
| `MASTODON_INSTANCE_URL` | Your Mastodon instance URL |
| `MASTODON_ACCESS_TOKEN` | Mastodon app token |
| `MASTODON_HANDLE` | e.g. `@bot@mastodon.social` |
| `BLUESKY_HANDLE` | e.g. `bot.bsky.social` (no `@`) |
| `BLUESKY_APP_PASSWORD` | Bluesky app password |
| `WEBSITE_URL` | Public URL of the web app |
| `SITE_NAME` | Displayed site name |
| `OTHER_LOCALE_URL` | URL of the other language instance, shown in the nav |
| `DB_PATH` | Path to the SQLite database (absolute path recommended in production) |
| `BOT_MIN_INTERVAL` | Minimum posting interval in minutes (default: 30) |
| `BOT_MAX_INTERVAL` | Maximum posting interval in minutes (default: 120) |
| `WIKIHOW_SITEMAP_URL` | WikiHow sitemap to scrape |
| `WIKIHOW_DOMAIN` | Domain used in sitemap URLs — `de.wikihow.com` for DE, `www.wikihow.com` for EN |
| `QUESTION_PREFIX` | Question prefix, e.g. `Kann KI` or `Can AI` |

Mastodon and Bluesky are both optional. The bot skips a platform if its credentials
are missing.

Note: for the English instance, the WikiHow sitemap lists articles under `www.wikihow.com`
(not `en.wikihow.com`), so `WIKIHOW_DOMAIN` must be set to `www.wikihow.com`. See
`.env.en.example` for the correct defaults.

### Run locally

```bash
# Initialise the database and load articles from WikiHow
uv run python -c "from database import init_db, store_articles; from scraper import scrape_all; init_db(); store_articles(scrape_all())"

# Start the web app
uv run uvicorn web.app:app --reload

# In a separate terminal: run the bot (won't post unless credentials are set)
uv run python bot.py
```

The web app runs at http://localhost:8000.

### Two instances (DE + EN)

Both instances share the same codebase. Use separate `.env` files and point each
process at the right one via the `DOTENV_PATH` environment variable:

```bash
DOTENV_PATH=.env.de uv run uvicorn web.app:app --port 8000 --reload
DOTENV_PATH=.env.en uv run uvicorn web.app:app --port 8001 --reload
```

See `.env.example` and `.env.en.example` for full templates.

### Content moderation

To remove existing articles that match the blocklist or non-action filter:

```bash
DOTENV_PATH=.env.de uv run python cleanup_blocklist.py
DOTENV_PATH=.env.en uv run python cleanup_blocklist.py
```

## Social media posting

Each bot cycle posts in two steps:

1. The question is posted as a standalone post with the correct language tag (`de` or `en`)
2. The vote link is posted as a direct reply to the question, with a clickable facet (Bluesky) or plain link (Mastodon)

Mastodon posts are sent with `visibility="public"` to ensure they appear on public timelines.
Make sure the Mastodon account's default post visibility is also set to Public in account preferences.

## Deployment

The `supervisord/` directory contains process configs for all four processes
(web + bot for each locale). The `Makefile` provides SSH shortcuts once you create
a `.uberspace` file with `UBERSPACE=user@host`:

```bash
make deploy          # pull latest, sync deps, restart web instances
make status          # show supervisord status for all 4 processes
make logs-web-de     # tail the German web log
make logs-bot-en     # tail the English bot log
```

For first-time server setup see `DEPLOY_UBERSPACE.md`.

## Project structure

```
bot.py                # Bot process: scrape articles, post questions
scraper.py            # WikiHow sitemap scraper with action-title filtering
database.py           # Database layer (sync for bot, async for web)
blocklist.py          # Politically incorrect term filter (DE + EN)
cleanup_blocklist.py  # One-off script: remove filtered articles from DB
mastodon_client.py    # Mastodon posting (question + reply with link)
bluesky_client.py     # Bluesky posting (question + reply with clickable link)
utils.py              # Shared helpers (localised vote CTA)
web/
  app.py              # FastAPI application
  og_image.py         # Open Graph image generator (retro DOS style)
  locales/            # Translation strings (de.py, en.py)
  templates/          # Jinja2 templates
  static/             # CSS, JS, fonts, vendor assets
supervisord/          # Process configs for production
deploy/               # Server setup and update scripts
seed_fake_data.py     # Marks random articles as posted for local testing
.env.example          # German instance config template
.env.en.example       # English instance config template
```

## License

MIT
