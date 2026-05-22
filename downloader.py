"""
BookFinder — Downloader

Resolves download URLs from either backend and downloads the file to disk.
"""

from __future__ import annotations

import logging
import re
import zipfile
import xml.etree.ElementTree as ET
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


def _read_epub_metadata(path: Path) -> dict:
    """
    Extract title and author from an EPUB's OPF metadata.
    Returns dict with 'title' and 'author' keys (empty strings if unreadable).
    """
    try:
        with zipfile.ZipFile(path, "r") as zf:
            # Find OPF file via container.xml
            container = zf.read("META-INF/container.xml").decode("utf-8", errors="replace")
            root = ET.fromstring(container)
            ns = {"c": "urn:oasis:names:tc:opendocument:xmlns:container"}
            opf_path = root.find(".//c:rootfile", ns)
            if opf_path is None:
                return {"title": "", "author": ""}
            opf_name = opf_path.get("full-path", "")

            opf_data = zf.read(opf_name).decode("utf-8", errors="replace")
            opf_root = ET.fromstring(opf_data)

            dc_ns = "http://purl.org/dc/elements/1.1/"
            title_el = opf_root.find(f".//{{{dc_ns}}}title")
            author_el = opf_root.find(f".//{{{dc_ns}}}creator")

            return {
                "title": (title_el.text or "").strip() if title_el is not None else "",
                "author": (author_el.text or "").strip() if author_el is not None else "",
            }
    except Exception as e:
        logger.debug("Could not read EPUB metadata: %s", e)
        return {"title": "", "author": ""}


def _titles_match(expected: str, actual: str) -> bool:
    """Loose match: normalize and check if one contains the other."""
    def norm(s: str) -> str:
        return re.sub(r"[^\w]", "", s.lower())
    a, b = norm(expected), norm(actual)
    if not a or not b:
        return True  # can't compare, assume OK
    return a in b or b in a


def download_book(book: dict, dest_dir: str | None = None) -> tuple[Path | None, str | None]:
    """
    Download a book to the local filesystem.

    Returns (path, warning) where warning is a human-readable string if the
    downloaded file metadata doesn't match the expected book, or None if OK.
    Returns (None, None) on download failure.
    """
    dest = Path(dest_dir or DOWNLOAD_DIR)
    dest.mkdir(parents=True, exist_ok=True)

    source = book.get("source", "?")
    title = book.get("title", "book")
    author = book.get("author", "")

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
        return None, None

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

        # Verify EPUB metadata matches expected book
        warning = None
        if ext == "epub":
            meta = _read_epub_metadata(filepath)
            actual_title = meta["title"]
            actual_author = meta["author"]
            if actual_title and not _titles_match(title, actual_title):
                warning = (
                    f"⚠️ *El archivo descargado no coincide con el libro seleccionado.*\n\n"
                    f"Esperado: _{title}_\n"
                    f"Contenido real: _{actual_title}_ — _{actual_author}_\n\n"
                    f"Z-Library tiene un archivo incorrecto para este libro."
                )
                logger.warning(
                    "Metadata mismatch: expected title=%r, got title=%r author=%r (id=%s)",
                    title, actual_title, actual_author, book_id,
                )

        return filepath, warning

    except Exception as e:
        print(f"\n  ❌ Download failed: {e}")
        if filepath.exists():
            filepath.unlink()
        return None, None
