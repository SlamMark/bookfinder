"""
BookFinder — Cover lookup on Open Library

Libgen results never carry cover art and Z-Library's is only available while
its API is reachable, so covers are looked up on Open Library (Internet
Archive): public, free and no account needed.

Matching is deliberately strict. A cover belonging to a different book is
worse than no cover at all, so a candidate is only accepted when its ISBN
matches — which identifies one exact edition — or when *both* title and author
match after normalisation. Anything short of that returns None.
"""

from __future__ import annotations

import logging
import re
import unicodedata

import requests

logger = logging.getLogger(__name__)

SEARCH_URL = "https://openlibrary.org/search.json"
# default=false makes Open Library 404 instead of serving a blank placeholder
COVER_URL = "https://covers.openlibrary.org/b/{key}/{value}-L.jpg?default=false"

# A lookup can chain up to four requests, and it runs while the user waits on
# the detail card, so keep each one short
_TIMEOUT = 8
# Open Library ranks loosely — searching "Dune" surfaces "Children of Dune"
# first — so look at a decent number of candidates and let the checks below
# discard them. `fields` keeps the reply small, so this stays one cheap request.
_MAX_CANDIDATES = 20

# ISBN-13 (978/979 + 10 digits) or ISBN-10 (9 digits + check digit or X)
_ISBN_RE = re.compile(r"(97[89]\d{10}|\d{9}[\dXx])")

# Cache lookups so paging back and forth doesn't re-query Open Library
_cache: dict[tuple[str, str], str | None] = {}


# ── Normalisation ────────────────────────────────────────────────────────────

def _norm(text: str) -> str:
    """Lowercase, strip accents and punctuation, collapse whitespace."""
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[^\w\s]", " ", text.lower())
    return re.sub(r"\s+", " ", text).strip()


def _title_variants(title: str) -> set[str]:
    """
    The normalised title, plus the part before any subtitle separator.

    Editions disagree on subtitles — "Sapiens" and "Sapiens: A Brief History
    of Humankind" are the same book — so both forms are considered.
    """
    variants = {_norm(title)}
    for sep in (":", " - ", "—"):
        if sep in (title or ""):
            variants.add(_norm(title.split(sep)[0]))
    return {v for v in variants if v}


def _titles_match(expected: str, candidate: str) -> bool:
    return bool(_title_variants(expected) & _title_variants(candidate))


def _author_tokens(author: str) -> set[str]:
    """Name tokens, dropping single-letter initials."""
    return {t for t in _norm(author).split() if len(t) > 1}


def _authors_match(expected: str, candidate: str) -> bool:
    """
    True when the shorter name is fully contained in the longer one.

    Accepts "Harari, Yuval Noah" vs "Yuval Noah Harari" and "Harari" vs the
    full name, but rejects different people who merely share a first name.
    """
    a, b = _author_tokens(expected), _author_tokens(candidate)
    if not a or not b:
        return False
    short, long_ = (a, b) if len(a) <= len(b) else (b, a)
    return short <= long_


def _first_isbn(raw: str) -> str | None:
    """Pull the first well-formed ISBN out of a metadata field."""
    for token in re.split(r"[^0-9Xx]+", (raw or "").replace("-", "")):
        if _ISBN_RE.fullmatch(token):
            return token
    return None


# ── Lookup ───────────────────────────────────────────────────────────────────

def _cover_exists(url: str) -> bool:
    """Check the cover is really there — Open Library 404s when it isn't."""
    try:
        resp = requests.head(url, timeout=_TIMEOUT, allow_redirects=True)
    except Exception as e:
        logger.warning("Open Library cover check failed: %s", e)
        return False
    return resp.status_code == 200 and resp.headers.get("content-type", "").startswith("image/")


def _query(params: dict) -> list[dict]:
    params = {**params, "fields": "title,author_name,cover_i", "limit": _MAX_CANDIDATES}
    try:
        resp = requests.get(SEARCH_URL, params=params, timeout=_TIMEOUT)
        resp.raise_for_status()
        return resp.json().get("docs", []) or []
    except Exception as e:
        logger.warning("Open Library search failed (%s): %s", params, e)
        return []


def _search_candidates(title: str, author: str) -> list[dict]:
    """
    Collect candidates, widening the query until something comes back.

    The `title` parameter matches almost literally, so a title carrying a
    subtitle finds nothing on its own; free text is the last resort. Widening
    only affects what we look at — every candidate still has to pass the same
    title and author check afterwards.
    """
    attempts: list[dict] = [{"title": title, "author": author}]

    main_title = re.split(r"[:\-—]", title, maxsplit=1)[0].strip()
    if main_title and main_title != title:
        attempts.append({"title": main_title, "author": author})

    attempts.append({"q": f"{title} {author}"})

    for params in attempts:
        docs = _query(params)
        if docs:
            return docs
    return []


def _lookup(title: str, author: str, isbn: str) -> str | None:
    isbn_code = _first_isbn(isbn)
    if isbn_code:
        url = COVER_URL.format(key="isbn", value=isbn_code)
        if _cover_exists(url):
            logger.info("Cover matched by ISBN %s for %r", isbn_code, title)
            return url
        logger.debug("No Open Library cover for ISBN %s", isbn_code)

    if not author:
        # Titles alone are far too ambiguous to trust
        logger.info("No author for %r — skipping Open Library search", title)
        return None

    docs = _search_candidates(title, author)
    for doc in docs:
        cover_id = doc.get("cover_i")
        if not cover_id:
            continue
        if not _titles_match(title, doc.get("title", "")):
            continue
        if not any(_authors_match(author, name) for name in doc.get("author_name", []) or []):
            continue
        logger.info(
            "Cover matched on Open Library: %r by %s", doc.get("title"), doc.get("author_name"),
        )
        return COVER_URL.format(key="id", value=cover_id)

    logger.info(
        "No Open Library cover matched %r by %r (%d candidates rejected)",
        title, author, len(docs),
    )
    return None


def find_cover_url(title: str, author: str = "", isbn: str = "") -> str | None:
    """
    Return an Open Library cover URL for this book, or None if none matches.

    Never guesses: an unverified candidate is discarded rather than shown.
    """
    if not title:
        return None

    key = (_norm(title), _norm(author))
    if key not in _cache:
        _cache[key] = _lookup(title, author, isbn)
    return _cache[key]
