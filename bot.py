#!/usr/bin/env python3
"""
BookFinder — Telegram Bot (Phase 2)

Flow:
  Text message  → search Z-Library + Libgen → list with buttons
  Tap result    → new message: cover + full details + [Descargar] [Volver]
  [Volver]      → deletes detail message (list stays visible)
  [Descargar]   → downloads file and sends it to the chat
"""

import asyncio
import logging
import re
from pathlib import Path

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from config import TELEGRAM_TOKEN, BOT_MAX_RESULTS
from downloader import download_book
from searcher_libgen import search_libgen
from searcher_zlib import get_book_details, search_zlibrary

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Per-chat results cache
_cache: dict[int, list[dict]] = {}

TELEGRAM_MAX_FILE_MB = 50


def _safe(text) -> str:
    """Strip Markdown-breaking characters from user-supplied text."""
    return re.sub(r"[*_`\[\]]", "", str(text or "")).strip()


# ── /start ────────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "📚 *BookFinder*\n\n"
        "Escríbeme el título de un libro y te busco resultados en Z\\-Library y Libgen\\.\n\n"
        "Toca un resultado para ver la ficha completa y descargarlo\\.",
        parse_mode="MarkdownV2",
    )


# ── Search ────────────────────────────────────────────────────────────────────

def _list_keyboard(books: list[dict]) -> InlineKeyboardMarkup:
    buttons = []
    for i, book in enumerate(books):
        icon = "🟡" if book["source"] == "zlibrary" else "🟢"
        title = _safe(book["title"])[:28]
        author = _safe(book.get("author", ""))[:15]
        ext = (book.get("extension") or "?").upper()
        size = book.get("size", "")
        label = f"{icon} {title} · {author} · {ext} {size}".strip(" ·")
        buttons.append([InlineKeyboardButton(label, callback_data=f"d:{i}")])
    return InlineKeyboardMarkup(buttons)


async def handle_search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.message.text.strip()
    chat_id = update.effective_chat.id

    msg = await update.message.reply_text(f"🔍 Buscando {query}…")

    results: list[dict] = []
    try:
        results.extend(search_zlibrary(query, max_results=BOT_MAX_RESULTS))
    except Exception as e:
        logger.warning("Z-Library error: %s", e)

    if len(results) < BOT_MAX_RESULTS:
        try:
            results.extend(
                search_libgen(query, max_results=BOT_MAX_RESULTS - len(results))
            )
        except Exception as e:
            logger.warning("Libgen error: %s", e)

    if not results:
        await msg.edit_text("❌ No encontré nada. Prueba con otro título.")
        return

    _cache[chat_id] = results[:BOT_MAX_RESULTS]

    await msg.edit_text(
        f"📚 *{_safe(query)}* — elige un resultado:",
        reply_markup=_list_keyboard(_cache[chat_id]),
        parse_mode="Markdown",
    )


# ── Detail view ───────────────────────────────────────────────────────────────

def _format_detail(book: dict, info: dict | None) -> str:
    b = (info or {}).get("book", {})

    lines = [f"📖 *{_safe(book['title'])}*"]

    author = _safe(b.get("author") or book.get("author", ""))
    if author:
        lines.append(f"✍️ {author}")

    desc = _safe(b.get("description", ""))
    if desc:
        if len(desc) > 380:
            desc = desc[:380].rsplit(" ", 1)[0] + "…"
        lines.append(f"\n_{desc}_")

    lines.append("")

    def row(icon, label, *keys, fallback=None):
        for key in keys:
            val = _safe(b.get(key) or "")
            if val:
                lines.append(f"{icon} *{label}:* {val}")
                return
        if fallback:
            lines.append(f"{icon} *{label}:* {_safe(fallback)}")

    row("📂", "Categorías",   "categories")
    row("📄", "Tipo",          "contentType", "content_type")
    row("📑", "Volumen",       "volume")
    row("📅", "Año",           "year",         fallback=book.get("year"))
    row("🌍", "Idioma",        "language",     fallback=book.get("language"))
    row("📚", "Serie",         "series")
    row("🏢", "Editorial",     "publisher",    fallback=book.get("publisher"))

    ext  = _safe(b.get("extension") or book.get("extension", "")).upper()
    size = _safe(b.get("filesizeString") or b.get("filesize_string") or book.get("size", ""))
    if ext or size:
        lines.append(f"📁 *Archivo:* {', '.join(filter(None, [ext, size]))}")

    cid   = _safe(b.get("ipfs_cid")        or b.get("ipfsCid", ""))
    cid_b = _safe(b.get("ipfs_cid_blake2b") or b.get("ipfsCidBlake2b", ""))
    if cid or cid_b:
        parts = []
        if cid:
            parts.append(f"`{cid[:24]}…`")
        if cid_b:
            parts.append(f"`{cid_b[:24]}…`")
        lines.append(f"🔗 *IPFS:* {', '.join(parts)}")

    return "\n".join(lines)


def _detail_keyboard(idx: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("⬇️ Descargar", callback_data=f"dl:{idx}"),
        InlineKeyboardButton("⬅️ Volver",    callback_data="back"),
    ]])


async def handle_detail(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    callback = update.callback_query
    await callback.answer()

    chat_id = update.effective_chat.id
    idx = int(callback.data.split(":")[1])
    books = _cache.get(chat_id, [])

    if idx >= len(books):
        await callback.answer("Sesión expirada. Haz una nueva búsqueda.", show_alert=True)
        return

    book = books[idx]

    # Fetch full details (sync → executor)
    info = None
    if book["source"] == "zlibrary":
        loop = asyncio.get_event_loop()
        info = await loop.run_in_executor(None, get_book_details, book)

    text = _format_detail(book, info)
    keyboard = _detail_keyboard(idx)

    # Cover URL: try search result first, then API response
    cover_url = None
    if book["source"] == "zlibrary":
        cover_url = (
            (book.get("_zlib_item") or {}).get("cover")
            or (info or {}).get("book", {}).get("cover")
        )

    send_kwargs = dict(
        chat_id=chat_id,
        reply_markup=keyboard,
        parse_mode="Markdown",
    )

    if cover_url:
        try:
            await context.bot.send_photo(photo=cover_url, caption=text, **send_kwargs)
            return
        except Exception as e:
            logger.warning("Failed to send cover photo: %s", e)

    await context.bot.send_message(text=text, **send_kwargs)


# ── Download ──────────────────────────────────────────────────────────────────

async def _edit_detail(callback, text: str) -> None:
    """Edit caption if it's a photo message, otherwise edit text."""
    try:
        await callback.edit_message_caption(caption=text, parse_mode="Markdown")
    except Exception:
        try:
            await callback.edit_message_text(text=text, parse_mode="Markdown")
        except Exception:
            pass


async def handle_download(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    callback = update.callback_query
    await callback.answer()

    chat_id = update.effective_chat.id
    idx = int(callback.data.split(":")[1])
    books = _cache.get(chat_id, [])

    if idx >= len(books):
        await callback.answer("Sesión expirada. Haz una nueva búsqueda.", show_alert=True)
        return

    book = books[idx]
    title = _safe(book["title"])

    await _edit_detail(callback, f"⏳ Descargando *{title}*…")

    loop = asyncio.get_event_loop()
    path: Path | None = await loop.run_in_executor(None, download_book, book)

    if path is None:
        await _edit_detail(callback, f"❌ No se pudo descargar *{title}*. Prueba otro resultado.")
        return

    size_mb = path.stat().st_size / (1024 * 1024)
    if size_mb > TELEGRAM_MAX_FILE_MB:
        path.unlink(missing_ok=True)
        await _edit_detail(callback, f"⚠️ El archivo pesa {size_mb:.1f} MB (límite Telegram: 50 MB).")
        return

    await _edit_detail(callback, f"📤 Enviando *{title}*…")

    try:
        caption = f"📖 *{title}*"
        if book.get("author"):
            caption += f"\n✍️ {_safe(book['author'])}"

        with open(path, "rb") as f:
            await context.bot.send_document(
                chat_id=chat_id,
                document=f,
                filename=path.name,
                caption=caption,
                parse_mode="Markdown",
            )
        await _edit_detail(callback, f"✅ *{title}* enviado.")
    except Exception as e:
        logger.error("Error sending file: %s", e)
        await _edit_detail(callback, "❌ Error al enviar el archivo.")
    finally:
        path.unlink(missing_ok=True)


# ── Back ──────────────────────────────────────────────────────────────────────

async def handle_back(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    callback = update.callback_query
    await callback.answer()
    try:
        await callback.message.delete()
    except Exception:
        pass


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    if not TELEGRAM_TOKEN:
        raise RuntimeError("TELEGRAM_TOKEN is not set in .env")

    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_search))
    app.add_handler(CallbackQueryHandler(handle_detail,  pattern=r"^d:\d+$"))
    app.add_handler(CallbackQueryHandler(handle_download, pattern=r"^dl:\d+$"))
    app.add_handler(CallbackQueryHandler(handle_back,    pattern=r"^back$"))

    logger.info("BookFinder bot started.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
