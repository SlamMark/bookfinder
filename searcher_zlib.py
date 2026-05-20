"""
BookFinder — Z-Library search backend

Uses our vendored zlib_client (official /eapi/ endpoints).
Returns a normalised list of book dicts.
"""

from __future__ import annotations

from typing import Optional

from zlib_client import Zlibrary
from config import ZLIB_EMAIL, ZLIB_PASSWORD


# ── Language code → Z-Library language name ──────────────────────────────────
_LANG_MAP: dict[str, str] = {
    "es": "spanish",
    "en": "english",
    "fr": "french",
    "de": "german",
    "it": "italian",
    "pt": "portuguese",
    "ca": "catalan",
    "ru": "russian",
    "zh": "chinese",
    "ja": "japanese",
    "ko": "korean",
    "ar": "arabic",
    "nl": "dutch",
    "pl": "polish",
    "sv": "swedish",
    "tr": "turkish",
}


# ── Module-level client (login once per process) ─────────────────────────────
_client: Optional[Zlibrary] = None


def _get_client() -> Optional[Zlibrary]:
    global _client
    if _client is not None:
        return _client
    if not ZLIB_EMAIL or not ZLIB_PASSWORD:
        return None
    client = Zlibrary(email=ZLIB_EMAIL, password=ZLIB_PASSWORD)
    if not client.isLoggedIn():
        return None
    _client = client
    return _client


def _book_to_dict(item: dict) -> dict:
    """Normalise a Z-Library book object into our standard dict format."""
    authors_raw = item.get("author", "") or ""
    return {
        "source":    "zlibrary",
        "topic":     item.get("categories", ""),
        "title":     item.get("title", ""),
        "author":    authors_raw,
        "year":      str(item.get("year", "")),
        "language":  item.get("language", ""),
        "extension": item.get("extension", ""),
        "size":      item.get("filesizeString", "") or str(item.get("filesize", "")),
        "pages":     str(item.get("pages", "")),
        "publisher": item.get("publisher", ""),
        "md5":       item.get("md5", ""),
        "mirrors":   [],
        "_zlib_item": item,  # keep original for download resolution
    }


def search_zlibrary(
    query: str,
    lang: Optional[str] = None,
    max_results: int = 25,
) -> list[dict]:
    """Search Z-Library and return a list of normalised book dicts."""
    client = _get_client()
    if client is None:
        return []

    languages = [_LANG_MAP[lang.lower()]] if lang and lang.lower() in _LANG_MAP else None

    response = client.search(message=query, languages=languages, limit=max_results)
    if not response or not response.get("success"):
        return []

    books = response.get("books", []) or []
    return [_book_to_dict(b) for b in books[:max_results]]


def resolve_download_url(book_dict: dict) -> str | None:
    """Resolve the direct download URL for a Z-Library book."""
    client = _get_client()
    if client is None:
        return None
    item = book_dict.get("_zlib_item")
    if item is None:
        return None
    try:
        return client.getDownloadLink(item)
    except Exception:
        return None
