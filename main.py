#!/usr/bin/env python3
"""
BookFinder — CLI

Usage:
    python main.py "El nombre del viento" --lang es
    python main.py "Sapiens" --lang en
    python main.py "1984"                          # any language
"""

from __future__ import annotations

import argparse
import sys

from config import MAX_RESULTS, DEFAULT_LANG
from searcher_libgen import search_libgen
from searcher_zlib import search_zlibrary
from downloader import download_book


# ── Colour helpers (ANSI) ────────────────────────────────────────────────────
BOLD  = "\033[1m"
DIM   = "\033[2m"
CYAN  = "\033[96m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED   = "\033[91m"
RESET = "\033[0m"


def _print_header():
    print(f"""
{BOLD}{CYAN}╔══════════════════════════════════════╗
║          📚  BookFinder  📚          ║
║     Libgen + Z-Library combined      ║
╚══════════════════════════════════════╝{RESET}
""")


def _print_table(results: list[dict]):
    """Print a nicely formatted table of results."""
    if not results:
        print(f"  {RED}No results found.{RESET}")
        return

    # Header
    print(f"  {BOLD}{'#':>3}  {'Source':<10} {'Title':<40} {'Author':<25} {'Lang':<6} {'Ext':<5} {'Size':<10} {'Year':<5}{RESET}")
    print(f"  {'─'*3}  {'─'*10} {'─'*40} {'─'*25} {'─'*6} {'─'*5} {'─'*10} {'─'*5}")

    for i, book in enumerate(results, 1):
        src = book["source"]
        src_color = GREEN if src == "libgen" else YELLOW
        title = book["title"][:38] + "…" if len(book["title"]) > 39 else book["title"]
        author = book["author"][:23] + "…" if len(book["author"]) > 24 else book["author"]

        print(
            f"  {BOLD}{i:>3}{RESET}  "
            f"{src_color}{src:<10}{RESET} "
            f"{title:<40} "
            f"{author:<25} "
            f"{book['language'][:5]:<6} "
            f"{book['extension']:<5} "
            f"{book['size']:<10} "
            f"{book['year']:<5}"
        )


def _pick_book(results: list[dict]) -> dict | None:
    """Prompt user to pick a book by number."""
    while True:
        try:
            choice = input(f"\n  {BOLD}Enter number to download (0 to cancel): {RESET}").strip()
            if choice == "0":
                return None
            idx = int(choice) - 1
            if 0 <= idx < len(results):
                return results[idx]
            print(f"  {RED}Invalid number. Try again.{RESET}")
        except (ValueError, EOFError):
            return None


def main():
    parser = argparse.ArgumentParser(
        description="📚 BookFinder — Search & download books from Libgen + Z-Library"
    )
    parser.add_argument("query", help="Book title, author or search term")
    parser.add_argument("--lang", "-l", default=DEFAULT_LANG,
                        help="Language code: es, en, fr, de, it, pt … (default: any)")
    parser.add_argument("--max", "-m", type=int, default=MAX_RESULTS,
                        help=f"Max results to display (default: {MAX_RESULTS})")
    parser.add_argument("--libgen-only", action="store_true",
                        help="Search only Libgen (skip Z-Library)")
    parser.add_argument("--zlib-only", action="store_true",
                        help="Search only Z-Library (skip Libgen)")
    args = parser.parse_args()

    _print_header()

    all_results: list[dict] = []
    lang = args.lang or None

    # ── Step 1: Search Libgen ────────────────────────────────────────────
    if not args.zlib_only:
        print(f"  🔍 Searching Libgen for {BOLD}'{args.query}'{RESET}" +
              (f" [{lang}]" if lang else "") + " …")
        try:
            libgen_results = search_libgen(args.query, lang=lang, max_results=args.max)
            print(f"     → Found {GREEN}{len(libgen_results)}{RESET} results on Libgen")
            all_results.extend(libgen_results)
        except Exception as e:
            print(f"     → {RED}Libgen error: {e}{RESET}")

    # ── Step 2: Search Z-Library (if needed / requested) ─────────────────
    if not args.libgen_only:
        need_zlib = args.zlib_only or len(all_results) < args.max
        if need_zlib:
            remaining = args.max - len(all_results)
            print(f"  🔍 Searching Z-Library for {BOLD}'{args.query}'{RESET}" +
                  (f" [{lang}]" if lang else "") + " …")
            try:
                zlib_results = search_zlibrary(args.query, lang=lang, max_results=remaining)
                print(f"     → Found {YELLOW}{len(zlib_results)}{RESET} results on Z-Library")
                all_results.extend(zlib_results)
            except Exception as e:
                print(f"     → {RED}Z-Library error: {e}{RESET}")

    # ── Step 3: Display results ──────────────────────────────────────────
    print()
    _print_table(all_results[:args.max])

    if not all_results:
        print(f"\n  {DIM}Nothing found. Try a broader search or different language.{RESET}")
        sys.exit(0)

    # ── Step 4: Pick and download ────────────────────────────────────────
    book = _pick_book(all_results[:args.max])
    if book is None:
        print(f"\n  {DIM}Cancelled.{RESET}")
        sys.exit(0)

    print(f"\n  📖 Selected: {BOLD}{book['title']}{RESET} — {book['author']}")
    result = download_book(book)

    if result:
        print(f"\n  🎉 Done! File ready at: {BOLD}{result}{RESET}\n")
    else:
        print(f"\n  {RED}Download failed. Try another result.{RESET}\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
