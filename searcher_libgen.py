"""
BookFinder — Libgen search backend

Searches Library Genesis using libgen-api-enhanced.
Returns a normalised list of book dicts.
"""

from __future__ import annotations
from typing import Optional

from libgen_api_enhanced import LibgenSearch, SearchTopic

from config import LIBGEN_MIRROR


# ── Language mapping ─────────────────────────────────────────────────────────
# Libgen stores full language names in English; we map common codes.
_LANG_MAP = {
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


def _resolve_lang(lang: str) -> str:
    """Convert a 2-letter code to the full Libgen language name."""
    return _LANG_MAP.get(lang.lower(), lang.lower())


def _book_to_dict(book, source_topic: str) -> dict:
    """Normalise a libgen Book object into our standard dict format."""
    return {
        "source":    "libgen",
        "topic":     source_topic,
        "title":     getattr(book, "title", ""),
        "author":    getattr(book, "author", ""),
        "year":      getattr(book, "year", ""),
        "language":  getattr(book, "language", ""),
        "extension": getattr(book, "extension", ""),
        "size":      getattr(book, "size", ""),
        "pages":     getattr(book, "pages", ""),
        "publisher": getattr(book, "publisher", ""),
        "md5":       getattr(book, "md5", ""),
        "mirrors":   getattr(book, "mirrors", []),
        "_book_obj": book,  # keep original for download resolution
    }


def search_libgen(
    query: str,
    lang: Optional[str] = None,
    max_results: int = 25,
) -> list[dict]:
    """
    Search Libgen across fiction + non-fiction topics.

    Parameters
    ----------
    query : str
        Title, author or general search term.
    lang : str | None
        Two-letter language code (e.g. 'es', 'en'). None = any.
    max_results : int
        Maximum results to return.

    Returns
    -------
    list[dict]  – normalised book dicts sorted by relevance.
    """
    s = LibgenSearch(mirror=LIBGEN_MIRROR)

    topics = [SearchTopic.FICTION, SearchTopic.LIBGEN]
    results: list[dict] = []

    # Build optional language filter
    filters = {}
    if lang:
        filters["language"] = _resolve_lang(lang)

    for topic in topics:
        try:
            if filters:
                books = s.search_title_filtered(
                    query,
                    filters,
                    exact_match=False,
                    search_in=[topic],
                )
            else:
                books = s.search_title(query, search_in=[topic])
        except Exception:
            # Mirror down or no results — continue with the next topic
            continue

        topic_label = "fiction" if topic == SearchTopic.FICTION else "non-fiction"
        for book in books or []:
            results.append(_book_to_dict(book, topic_label))

    # Deduplicate by md5
    seen_md5: set[str] = set()
    unique: list[dict] = []
    for r in results:
        md5 = r.get("md5", "")
        if md5 and md5 in seen_md5:
            continue
        seen_md5.add(md5)
        unique.append(r)

    return unique[:max_results]


def resolve_download_url(book_dict: dict) -> str | None:
    """
    Resolve a direct HTTP download link for a Libgen result.

    Returns the URL string or None on failure.
    """
    book = book_dict.get("_book_obj")
    if book is None:
        return None
    try:
        book.resolve_direct_download_link()
        return book.resolved_download_link
    except Exception:
        return getattr(book, "tor_download_link", None)
