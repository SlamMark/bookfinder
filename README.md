# 📚 BookFinder

Search books on **Z-Library + Libgen**, convert them with Calibre and send them
straight to your Kindle — from the command line or from a Telegram bot.

## Features

- 🔍 Combined search across Z-Library and Libgen (selectable per user)
- 🤖 Telegram bot with paginated results, cover art, synopsis and metadata
- 🔐 Admin approval system — new users request access, you approve or reject
- 📖 Format conversion via Calibre (`epub`, `mobi`, `azw3`, `pdf`)
- 📨 Send to Kindle by email, with cover and content validation before sending
- 🐳 Dockerised, auto-deployed to an LXC host on every push to `main`

## Quick Start

### Telegram bot (Docker — recommended)

```bash
git clone <repo> bookfinder && cd bookfinder
cp .env.example .env
nano .env          # Z-Library credentials, Telegram token, admin ID, SMTP
docker compose up -d --build
```

Then message your bot on Telegram. The first message from a new user creates an
access request that you approve from your own chat.

### CLI

```bash
pip install -r requirements.txt
cp .env.example .env
nano .env          # fill in ZLIB_EMAIL and ZLIB_PASSWORD

python main.py "El nombre del viento" --lang es
```

## CLI usage

```bash
python main.py "Sapiens"                          # any language
python main.py "Cien años de soledad" --lang es   # Spanish only
python main.py "Atomic Habits" --lang en --max 10 # cap results
python main.py "1984" --libgen-only               # no Z-Library account needed
python main.py "El principito" --zlib-only --lang es
```

## Bot commands

| Command | What it does |
|---|---|
| `/start`, `/help` | Show the command list |
| `/setsource` | Choose search backend: both, Z-Library only, or Libgen only |
| `/setformat` | Set your default download/send format |
| `/setkindle you@kindle.com` | Save your Kindle address |
| `/testkindle` | Send a test file to diagnose your Kindle setup |
| `/myid` | Show your Telegram ID |

**Flow:** send a book title → pick a result from the paginated list → detail view
with cover and synopsis → **⬇️ Descargar** (file in chat) or **📨 Enviar** (email
to your Kindle). Both ask which format you want first.

## Kindle setup

1. Enable 2FA on your Google account and create an **App Password**
   (Google Account → Security → App Passwords). Put it in `SMTP_PASS`.
2. In Amazon: *Manage Your Content and Devices → Preferences → Personal Document
   Settings → Approved Personal Document E-mail List* → add your `SMTP_FROM`
   (or `SMTP_USER`) address.
3. In the bot: `/setkindle you@kindle.com`, then `/testkindle` to verify.

Before emailing an EPUB, BookFinder injects the correct title/author with
`ebook-meta`, verifies the file actually contains a cover image, and checks that
its embedded metadata matches the book you selected — Z-Library occasionally
serves the wrong file. If either check fails the send is aborted and you're told
why, rather than silently getting a broken book on your device.

## Configuration (.env)

| Variable | Description | Default |
|---|---|---|
| `ZLIB_EMAIL` | Z-Library login email | *(required for Z-Lib)* |
| `ZLIB_PASSWORD` | Z-Library password | *(required for Z-Lib)* |
| `TELEGRAM_TOKEN` | Bot token from @BotFather | *(required for bot)* |
| `TELEGRAM_ADMIN_ID` | Your Telegram ID — receives access requests | *(required for approvals)* |
| `SMTP_HOST` | SMTP server | `smtp.gmail.com` |
| `SMTP_PORT` | SMTP port | `587` |
| `SMTP_USER` | SMTP account | *(required for Kindle)* |
| `SMTP_PASS` | App password | *(required for Kindle)* |
| `SMTP_FROM` | Sender shown to Amazon — must be an approved sender | `SMTP_USER` |
| `DOWNLOAD_DIR` | Where to save files | `./downloads` |
| `LIBGEN_MIRROR` | Libgen mirror (li, bz, gs) | `li` |
| `DEFAULT_LANG` | Default language code | *(any)* |
| `MAX_RESULTS` | Max results shown in CLI | `15` |
| `BOT_MAX_RESULTS` | Result buttons per page in the bot | `8` |

Use `/myid` in the bot to find your `TELEGRAM_ADMIN_ID`.

## Project structure

```
bookfinder/
├── bot.py               # Telegram bot — search, access control, download, send
├── main.py              # CLI entry point
├── searcher_zlib.py     # Z-Library search backend
├── searcher_libgen.py   # Libgen search backend
├── zlib_client.py       # Vendored Z-Library /eapi/ client
├── downloader.py        # URL resolution, download, EPUB cover & metadata checks
├── converter.py         # Calibre ebook-convert / ebook-meta wrappers
├── mailer.py            # SMTP send to Kindle with retries
├── user_settings.py     # Per-user prefs & approval status (JSON)
├── config.py            # Settings & credential loader
├── Dockerfile           # python:3.11-slim + Calibre
├── docker-compose.yml   # Bot service with persistent volumes
├── .github/workflows/   # Deploy to LXC over Tailscale on push to main
├── data/                # user_settings.json (persisted, git-ignored)
└── downloads/           # Downloaded books land here (git-ignored)
```

## Deployment

Pushing to `main` triggers `.github/workflows/deploy.yml`, which joins the
Tailscale network, SSHes into the LXC host and runs
`git pull && docker compose up -d --build` in `/opt/bookfinder`.

Required repo secrets: `TS_OAUTH_CLIENT_ID`, `TS_OAUTH_SECRET`, `LXC_HOST`,
`LXC_USER`, `SSH_PRIVATE_KEY`.

## Known issues

- **Search sessions are in-memory**, so restarting the bot invalidates result
  lists from earlier messages. Their buttons now explain that the session
  expired instead of doing nothing, but you have to search again.
