"""
BookFinder — Downloader

Resolves download URLs from either backend and downloads the file to disk.
"""

from __future__ import annotations

import logging
import re
import requests
from pathlib import Path

logger = logging.getLogger(__name__)

from config import DOWNLOAD_DIR
from searcher_libgen import resolve_download_url as libgen_resolve
from searcher_zlib import resolve_download_url as zlib_resolve


def _sanitise_filename(name: str) -> str:
    """Remove or replace characters that are problematic in file names."""
    name = re.sub(r'[<>:"/\\|?*]', '_', name)
    name = re.sub(r'\s+', ' ', name).strip()
    return name[:200]  # cap length


def resolve_url(book: dict) -> str | None:
    """Pick the right resolver based on source."""
    if book["source"] == "libgen":
        return libgen_resolve(book)
    elif book["source"] == "zlibrary":
        return zlib_resolve(book)
    return None


def download_book(book: dict, dest_dir: str | None = None) -> Path | None:
    """
    Download a book to the local filesystem.

    Parameters
    ----------
    book : dict
        A normalised book dict from either search backend.
    dest_dir : str | None
        Override destination directory. Defaults to DOWNLOAD_DIR from config.

    Returns
    -------
    Path to the downloaded file, or None on failure.
    """
    dest = Path(dest_dir or DOWNLOAD_DIR)
    dest.mkdir(parents=True, exist_ok=True)

    source = book.get("source", "?")
    title = book.get("title", "book")
    author = book.get("author", "")

    # Log the exact book identity being downloaded for debugging
    zlib_item = book.get("_zlib_item") or {}
    book_id = zlib_item.get("id") or book.get("md5") or "?"
    book_hash = zlib_item.get("hash", "")
    logger.info(
        "Resolving download: source=%s id=%s hash=%s title=%r author=%r",
        source, book_id, book_hash, title, author,
    )

    print(f"  ⏳ Resolving download URL …")
    url = resolve_url(book)
    if not url:
        logger.error("Could not resolve download URL: source=%s id=%s title=%r", source, book_id, title)
        print("  ❌ Could not resolve a download URL.")
        return None

    logger.info("Download URL resolved: %s", url)

    ext = book.get("extension", "epub").lower()
    filename = _sanitise_filename(f"{title} - {author}".strip(" -")) + f".{ext}"
    filepath = dest / filename

    print(f"  ⬇️  Downloading: {filename}")
    try:
        resp = requests.get(url, stream=True, timeout=120, allow_redirects=True)
        logger.info("HTTP %s for %s (final URL: %s)", resp.status_code, filename, resp.url)
        resp.raise_for_status()

        total = int(resp.headers.get("content-length", 0))
        downloaded = 0

        with open(filepath, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)
                downloaded += len(chunk)
                if total:
                    pct = downloaded * 100 // total
                    bar = "█" * (pct // 3) + "░" * (33 - pct // 3)
                    print(f"\r  [{bar}] {pct}%", end="", flush=True)

        print(f"\n  ✅ Saved to: {filepath}")
        return filepath

    except Exception as e:
        print(f"\n  ❌ Download failed: {e}")
        if filepath.exists():
            filepath.unlink()
        return None
