"""
BookFinder — Z-Library search backend

Uses our vendored zlib_client (official /eapi/ endpoints).
Returns a normalised list of book dicts.
"""

from __future__ import annotations

import logging
from typing import Optional

from zlib_client import Zlibrary
from config import ZLIB_DOMAIN, ZLIB_EMAIL, ZLIB_PASSWORD

logger = logging.getLogger(__name__)


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
    """
    Log in once per process and cache the client.

    Every failure path is logged: a silent None here makes the whole backend
    disappear from search results with no other symptom, and Libgen quietly
    covers for it — which looks like "no covers" rather than "no Z-Library".
    """
    global _client
    if _client is not None:
        return _client

    if not ZLIB_EMAIL or not ZLIB_PASSWORD:
        logger.error("Z-Library disabled: ZLIB_EMAIL or ZLIB_PASSWORD not set in .env")
        return None

    try:
        # Log in explicitly rather than via the constructor, so we can report why
        client = Zlibrary(domain=ZLIB_DOMAIN)
        response = client.login(ZLIB_EMAIL, ZLIB_PASSWORD)
    except Exception as e:
        logger.error("Z-Library login request to %s failed: %s", ZLIB_DOMAIN, e)
        return None

    if not client.isLoggedIn():
        # A rejected login has no user object, so nothing secret is logged here
        logger.error(
            "Z-Library login rejected by %s for %s: %s",
            ZLIB_DOMAIN, ZLIB_EMAIL, (response or {}).get("error") or response,
        )
        return None

    logger.info("Z-Library login OK (%s)", ZLIB_DOMAIN)
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
        "cover":     item.get("cover", "") or "",
        # Z-Library puts ISBNs in "identifier", sometimes several comma-separated
        "isbn":      item.get("identifier", "") or item.get("isbn", "") or "",
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

    try:
        response = client.search(message=query, languages=languages, limit=max_results)
    except Exception as e:
        logger.error("Z-Library search request failed for %r: %s", query, e)
        return []

    if not response or not response.get("success"):
        logger.warning(
            "Z-Library search failed for %r: %s",
            query, (response or {}).get("error") or response,
        )
        return []

    books = response.get("books", []) or []
    logger.info("Z-Library returned %d results for %r", len(books), query)
    return [_book_to_dict(b) for b in books[:max_results]]


def get_book_details(book_dict: dict) -> dict | None:
    """Fetch full book info from Z-Library (description, series, IPFS, etc.)."""
    client = _get_client()
    if client is None:
        return None
    item = book_dict.get("_zlib_item")
    if item is None:
        return None
    try:
        return client.getBookInfo(item["id"], item["hash"])
    except Exception:
        return None


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
