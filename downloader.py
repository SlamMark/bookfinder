"""
BookFinder — Downloader

Resolves download URLs from either backend and downloads the file to disk.
"""

from __future__ import annotations

import re
import requests
from pathlib import Path

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

    print(f"  ⏳ Resolving download URL …")
    url = resolve_url(book)
    if not url:
        print("  ❌ Could not resolve a download URL.")
        return None

    ext = book.get("extension", "epub").lower()
    title = book.get("title", "book")
    author = book.get("author", "")
    filename = _sanitise_filename(f"{title} - {author}".strip(" -")) + f".{ext}"
    filepath = dest / filename

    print(f"  ⬇️  Downloading: {filename}")
    try:
        resp = requests.get(url, stream=True, timeout=120, allow_redirects=True)
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
