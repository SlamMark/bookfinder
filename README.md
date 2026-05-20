# 📚 BookFinder

Search and download books from **Libgen + Z-Library** in a single command.

## Quick Start

```bash
# 1. Clone / copy the project
cd bookfinder

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure Z-Library credentials
cp .env.example .env
nano .env  # fill in ZLIB_EMAIL and ZLIB_PASSWORD

# 4. Search!
python main.py "El nombre del viento" --lang es
```

## Usage

```bash
# Search in any language
python main.py "Sapiens"

# Search in Spanish only
python main.py "Cien años de soledad" --lang es

# Search in English, max 10 results
python main.py "Atomic Habits" --lang en --max 10

# Only search Libgen (no Z-Library account needed)
python main.py "1984" --libgen-only

# Only search Z-Library
python main.py "El principito" --zlib-only --lang es
```

## How it works

1. Searches **Libgen** first (fiction + non-fiction, no account needed)
2. If not enough results, searches **Z-Library** as fallback (needs free account)
3. Shows a combined results table with source, title, author, language, format and size
4. You pick a number → it downloads the file

## Configuration (.env)

| Variable | Description | Default |
|---|---|---|
| `ZLIB_EMAIL` | Z-Library login email | *(required for Z-Lib)* |
| `ZLIB_PASSWORD` | Z-Library password | *(required for Z-Lib)* |
| `DOWNLOAD_DIR` | Where to save files | `./downloads` |
| `LIBGEN_MIRROR` | Libgen mirror (li, bz, gs) | `li` |
| `DEFAULT_LANG` | Default language code | *(any)* |
| `MAX_RESULTS` | Max results shown | `15` |

## Project Structure

```
bookfinder/
├── main.py              # CLI entry point
├── searcher_libgen.py   # Libgen search backend
├── searcher_zlib.py     # Z-Library search backend
├── downloader.py        # URL resolution + file download
├── config.py            # Settings & credential loader
├── .env.example         # Template for credentials
├── .env                 # Your actual credentials (git-ignored)
├── requirements.txt     # Python dependencies
└── downloads/           # Downloaded books land here
```

## Next Steps (Fase 2)

- [ ] Telegram bot wrapper (`bot.py`) — search and download from your phone
- [ ] Auto-convert with Calibre (`ebook-convert`)
- [ ] Send to Kindle via USB or email
