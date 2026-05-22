"""
BookFinder — Downloader

Resolves download URLs from either backend and downloads the file to disk.
"""

from __future__ import annotations

import logging
import re
import unicodedata
import zipfile
import xml.etree.ElementTree as ET
import requests
from pathlib import Path

logger = logging.getLogger(__name__)

from config import DOWNLOAD_DIR
from searcher_libgen import resolve_download_url as libgen_resolve
from searcher_zlib import resolve_download_url as zlib_resolve


def _sanitise_filename(name: str) -> str:
    """Normalize unicode to ASCII, strip problematic chars, cap length."""
    name = unicodedata.normalize("NFKD", name)
    name = name.encode("ascii", errors="ignore").decode("ascii")
    name = re.sub(r'[<>:"/\\|?*]', '', name)
    name = re.sub(r'\s+', ' ', name).strip()
    return name[:120]


def resolve_url(book: dict) -> str | None:
    """Pick the right resolver based on source."""
    if book["source"] == "libgen":
        return libgen_resolve(book)
    elif book["source"] == "zlibrary":
        return zlib_resolve(book)
    return None


def _parse_opf(path: Path) -> tuple[ET.Element | None, str, list[str]]:
    """
    Open EPUB and return (opf_root, opf_dir, zip_namelist).
    Returns (None, "", []) on failure.
    """
    try:
        with zipfile.ZipFile(path, "r") as zf:
            container = zf.read("META-INF/container.xml").decode("utf-8", errors="replace")
            root = ET.fromstring(container)
            ns = {"c": "urn:oasis:names:tc:opendocument:xmlns:container"}
            rootfile_el = root.find(".//c:rootfile", ns)
            if rootfile_el is None:
                return None, "", []
            opf_path = rootfile_el.get("full-path", "")
            opf_dir = str(Path(opf_path).parent).replace("\\", "/")
            if opf_dir == ".":
                opf_dir = ""
            opf_data = zf.read(opf_path).decode("utf-8", errors="replace")
            opf_root = ET.fromstring(opf_data)
            namelist = zf.namelist()
            return opf_root, opf_dir, namelist
    except Exception as e:
        logger.debug("Could not parse EPUB OPF: %s", e)
        return None, "", []


def _read_epub_metadata(path: Path) -> dict:
    """Extract title and author from an EPUB's OPF metadata."""
    opf_root, _, _ = _parse_opf(path)
    if opf_root is None:
        return {"title": "", "author": ""}
    dc_ns = "http://purl.org/dc/elements/1.1/"
    title_el = opf_root.find(f".//{{{dc_ns}}}title")
    author_el = opf_root.find(f".//{{{dc_ns}}}creator")
    return {
        "title": (title_el.text or "").strip() if title_el is not None else "",
        "author": (author_el.text or "").strip() if author_el is not None else "",
    }


def check_epub_cover(path: Path) -> bool:
    """
    Returns True if the EPUB contains a cover image referenced in the manifest.
    Checks EPUB3 (properties="cover-image"), EPUB2 (<meta name="cover">), and
    common fallback (item id containing "cover" with image media-type).
    """
    opf_root, opf_dir, namelist = _parse_opf(path)
    if opf_root is None:
        logger.warning("Could not parse OPF for cover check: %s", path.name)
        return False

    opf_ns = "http://www.idpf.org/2007/opf"

    def resolve_href(href: str) -> str:
        return f"{opf_dir}/{href}" if opf_dir else href

    def href_in_zip(href: str) -> bool:
        full = resolve_href(href)
        if full in namelist:
            return True
        full_lower = full.lower()
        return any(n.lower() == full_lower for n in namelist)

    # EPUB3: properties="cover-image"
    for item in opf_root.findall(f".//{{{opf_ns}}}item"):
        if "cover-image" in (item.get("properties") or ""):
            href = item.get("href", "")
            if href_in_zip(href):
                logger.debug("Cover found (EPUB3 properties): %s", href)
                return True
            logger.warning("Cover href %r declared but missing from archive", href)
            return False

    # EPUB2: <meta name="cover" content="item-id"/>
    for meta in opf_root.findall(f".//{{{opf_ns}}}meta"):
        if meta.get("name") == "cover":
            cover_id = meta.get("content", "")
            for item in opf_root.findall(f".//{{{opf_ns}}}item"):
                if item.get("id") == cover_id:
                    href = item.get("href", "")
                    if href_in_zip(href):
                        logger.debug("Cover found (EPUB2 meta): %s", href)
                        return True
                    logger.warning("Cover href %r declared but missing from archive", href)
                    return False

    # Fallback: item id contains "cover" with image media-type
    for item in opf_root.findall(f".//{{{opf_ns}}}item"):
        item_id = (item.get("id") or "").lower()
        media = item.get("media-type") or ""
        if "cover" in item_id and "image" in media:
            href = item.get("href", "")
            if href_in_zip(href):
                logger.debug("Cover found (fallback id): %s", href)
                return True

    logger.warning("No cover image found in EPUB manifest: %s", path.name)
    return False


def _titles_match(expected: str, actual: str) -> bool:
    """Loose match: normalize and check if one contains the other."""
    def norm(s: str) -> str:
        return re.sub(r"[^\w]", "", s.lower())
    a, b = norm(expected), norm(actual)
    if not a or not b:
        return True
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

    url = resolve_url(book)
    if not url:
        logger.error("Could not resolve download URL: source=%s id=%s title=%r", source, book_id, title)
        return None, None

    logger.info("Download URL resolved: %s", url)

    ext = book.get("extension", "epub").lower()
    # Format: "Author - Title.ext" with ASCII-safe chars
    author_part = _sanitise_filename(author)
    title_part = _sanitise_filename(title)
    base = f"{author_part} - {title_part}".strip(" -") or "book"
    filename = base + f".{ext}"
    filepath = dest / filename

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

        print()
        logger.info("Saved %s (%.2f MB)", filepath.name, downloaded / 1024 / 1024)

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
        logger.error("Download failed: %s", e)
        if filepath.exists():
            filepath.unlink()
        return None, None
