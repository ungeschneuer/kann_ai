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
3. Posts the question to Mastodon and/or Bluesky with a link to the website
4. Marks the article as posted so it is never repeated

The web app is independent — it shows all scraped articles regardless of posting status.
Visitors vote yes or no; results appear once a question reaches 3 votes.

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
| `LOCALE` | `de` or `en` |
| `MASTODON_INSTANCE_URL` | Your Mastodon instance URL |
| `MASTODON_ACCESS_TOKEN` | Mastodon app token |
| `MASTODON_HANDLE` | e.g. `@bot@mastodon.social` |
| `BLUESKY_HANDLE` | e.g. `bot.bsky.social` |
| `BLUESKY_APP_PASSWORD` | Bluesky app password |
| `WEBSITE_URL` | Public URL of the web app |
| `SITE_NAME` | Displayed site name |
| `DB_PATH` | Path to the SQLite database (absolute path recommended in production) |
| `BOT_MIN_INTERVAL` | Minimum posting interval in minutes (default: 30) |
| `BOT_MAX_INTERVAL` | Maximum posting interval in minutes (default: 120) |
| `WIKIHOW_SITEMAP_URL` | WikiHow sitemap to scrape |
| `WIKIHOW_DOMAIN` | WikiHow domain, e.g. `de.wikihow.com` |
| `QUESTION_PREFIX` | Question prefix, e.g. `Kann KI` or `Can AI` |

Mastodon and Bluesky are both optional. The bot skips a platform if its credentials
are missing.

### Run locally

```bash
# Initialise the database
uv run python -c "from database import init_db; init_db()"

# Load articles from WikiHow (takes a few seconds)
uv run python -c "from scraper import scrape_all; from database import store_articles; store_articles(scrape_all())"

# Mark some articles as posted for testing, so the site has content to show
uv run python seed_fake_data.py 30

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

## Project structure

```
bot.py               # Bot process: scrape articles, post questions
scraper.py           # WikiHow sitemap scraper
database.py          # Database layer (sync for bot, async for web)
mastodon_client.py   # Mastodon posting
bluesky_client.py    # Bluesky posting
utils.py             # Shared helpers
web/
  app.py             # FastAPI application
  og_image.py        # Open Graph image generator (retro DOS style)
  locales/           # Translation strings (de.py, en.py)
  templates/         # Jinja2 templates
  static/            # CSS, JS, fonts, vendor assets
supervisord/         # Process configs for production
deploy/              # Server setup and update scripts
seed_fake_data.py    # Marks random articles as posted for local testing
.env.example         # German instance config template
.env.en.example      # English instance config template
```

## License

MIT
