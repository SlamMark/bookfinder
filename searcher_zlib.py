"""
BookFinder — Z-Library search backend

Searches Z-Library using the 'zlibrary' async wrapper.
Returns a normalised list of book dicts.
"""

from __future__ import annotations

import asyncio
from typing import Optional

import zlibrary
from zlibrary import Language, Extension

from config import ZLIB_EMAIL, ZLIB_PASSWORD


# ── Language code → zlibrary.Language mapping ────────────────────────────────
_LANG_MAP: dict[str, Language] = {
    "es": Language.SPANISH,
    "en": Language.ENGLISH,
    "fr": Language.FRENCH,
    "de": Language.GERMAN,
    "it": Language.ITALIAN,
    "pt": Language.PORTUGUESE,
    "ru": Language.RUSSIAN,
    "zh": Language.CHINESE,
    "ja": Language.JAPANESE,
    "ko": Language.KOREAN,
    "ar": Language.ARABIC,
    "nl": Language.DUTCH,
    "pl": Language.POLISH,
    "sv": Language.SWEDISH,
    "tr": Language.TURKISH,
}


def _result_to_dict(item: dict) -> dict:
    """Normalise a zlibrary search-result item into our standard format."""
    authors_raw = item.get("authors") or []
    if isinstance(authors_raw, list):
        author_str = ", ".join(a.get("author", "") for a in authors_raw if isinstance(a, dict))
    else:
        author_str = str(authors_raw)

    return {
        "source":    "zlibrary",
        "topic":     "",
        "title":     item.get("name", ""),
        "author":    author_str,
        "year":      item.get("year", ""),
        "language":  item.get("language", ""),
        "extension": item.get("extension", ""),
        "size":      item.get("size", ""),
        "pages":     "",
        "publisher": item.get("publisher", ""),
        "md5":       "",
        "mirrors":   [],
        "_zlib_item": item,  # keep original for later fetching / download
    }


async def _search_async(
    query: str,
    lang: Optional[str] = None,
    max_results: int = 25,
) -> list[dict]:
    """Internal async search."""
    if not ZLIB_EMAIL or not ZLIB_PASSWORD:
        return []

    lib = zlibrary.AsyncZlib()
    await lib.login(ZLIB_EMAIL, ZLIB_PASSWORD)

    kwargs: dict = {"q": query, "count": max_results}
    if lang and lang.lower() in _LANG_MAP:
        kwargs["lang"] = [_LANG_MAP[lang.lower()]]

    paginator = await lib.search(**kwargs)
    result_set = await paginator.next()

    results: list[dict] = []
    for item in result_set or []:
        results.append(_result_to_dict(item))

    return results[:max_results]


def search_zlibrary(
    query: str,
    lang: Optional[str] = None,
    max_results: int = 25,
) -> list[dict]:
    """
    Synchronous wrapper that searches Z-Library.

    Parameters
    ----------
    query : str
        Title, author or general search term.
    lang : str | None
        Two-letter language code (e.g. 'es'). None = any.
    max_results : int
        Maximum number of results to return.

    Returns
    -------
    list[dict]  – normalised book dicts.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        # Already inside an event loop (e.g. Jupyter, bot)
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            return pool.submit(
                asyncio.run, _search_async(query, lang, max_results)
            ).result()
    else:
        return asyncio.run(_search_async(query, lang, max_results))


async def resolve_download_url_async(book_dict: dict) -> str | None:
    """
    Fetch the full book record from Z-Library and return the download URL.
    """
    item = book_dict.get("_zlib_item")
    if item is None:
        return None

    try:
        book = await item.fetch()
        return book.get("download_url")
    except Exception:
        return None


def resolve_download_url(book_dict: dict) -> str | None:
    """Synchronous wrapper for resolve_download_url_async."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            return pool.submit(
                asyncio.run, resolve_download_url_async(book_dict)
            ).result()
    else:
        return asyncio.run(resolve_download_url_async(book_dict))
