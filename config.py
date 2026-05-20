"""
BookFinder — Configuration

Credentials and default settings loaded from environment variables or .env file.
"""

import os
from pathlib import Path

# ── Load .env file if present ────────────────────────────────────────────────
_env_path = Path(__file__).parent / ".env"
if _env_path.exists():
    for line in _env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())

# ── Z-Library credentials ────────────────────────────────────────────────────
ZLIB_EMAIL = os.environ.get("ZLIB_EMAIL", "")
ZLIB_PASSWORD = os.environ.get("ZLIB_PASSWORD", "")

# ── Download settings ────────────────────────────────────────────────────────
DOWNLOAD_DIR = os.environ.get("DOWNLOAD_DIR", str(Path(__file__).parent / "downloads"))

# ── Libgen mirror (li, bz, gs, etc.) ────────────────────────────────────────
LIBGEN_MIRROR = os.environ.get("LIBGEN_MIRROR", "li")

# ── Defaults ─────────────────────────────────────────────────────────────────
DEFAULT_LANG = os.environ.get("DEFAULT_LANG", "")       # empty = any language
MAX_RESULTS  = int(os.environ.get("MAX_RESULTS", "15"))  # max results to show
