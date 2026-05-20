#!/usr/bin/env python3
"""
BookFinder — Telegram Bot (Phase 2 + 3)

Flow:
  Text message  → search Z-Library + Libgen → list with buttons
  Tap result    → new message: cover + full details + [Descargar] [Enviar] [Volver]
  [Descargar]   → new message: format selection → download + Calibre convert → send file
  [Enviar]      → placeholder (Phase 3)
  [Volver]      → deletes detail message (list stays visible)
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
from converter import SUPPORTED_FORMATS, convert
from downloader import download_book
from searcher_libgen import search_libgen
from searcher_zlib import get_book_details, search_zlibrary

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

_cache: dict[int, list[dict]] = {}

TELEGRAM_MAX_FILE_MB = 50


def _safe(text) -> str:
    """Strip Markdown-breaking characters from user-supplied text."""
    return re.sub(r"[*_`\[\]]", "", str(text or "")).strip()


# ── /start ────────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "📚 *BookFinder*\n\n"
        "Escríbeme el título de un libro y te busco resultados en Z-Library y Libgen.\n\n"
        "Toca un resultado para ver la ficha completa y descargarlo.",
        parse_mode="Markdown",
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

    row("📂", "Categorías",  "categories")
    row("📄", "Tipo",         "contentType", "content_type")
    row("📑", "Volumen",      "volume")
    row("📅", "Año",          "year",         fallback=book.get("year"))
    row("🌍", "Idioma",       "language",     fallback=book.get("language"))
    row("📚", "Serie",        "series")
    row("🏢", "Editorial",    "publisher",    fallback=book.get("publisher"))

    ext  = _safe(b.get("extension") or book.get("extension", "")).upper()
    size = _safe(b.get("filesizeString") or b.get("filesize_string") or book.get("size", ""))
    if ext or size:
        lines.append(f"📁 *Archivo:* {', '.join(filter(None, [ext, size]))}")

    cid   = _safe(b.get("ipfs_cid")         or b.get("ipfsCid", ""))
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
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⬇️ Descargar", callback_data=f"dl:{idx}"),
            InlineKeyboardButton("📨 Enviar",    callback_data=f"send:{idx}"),
        ],
        [InlineKeyboardButton("⬅️ Volver", callback_data="back")],
    ])


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

    info = None
    if book["source"] == "zlibrary":
        loop = asyncio.get_event_loop()
        info = await loop.run_in_executor(None, get_book_details, book)

    text = _format_detail(book, info)
    keyboard = _detail_keyboard(idx)

    cover_url = None
    if book["source"] == "zlibrary":
        cover_url = (
            (book.get("_zlib_item") or {}).get("cover")
            or (info or {}).get("book", {}).get("cover")
        )

    send_kwargs = dict(chat_id=chat_id, reply_markup=keyboard, parse_mode="Markdown")

    if cover_url:
        try:
            await context.bot.send_photo(photo=cover_url, caption=text, **send_kwargs)
            return
        except Exception as e:
            logger.warning("Cover photo failed: %s", e)

    await context.bot.send_message(text=text, **send_kwargs)


# ── Format selection ──────────────────────────────────────────────────────────

def _format_keyboard(idx: int, original_fmt: str) -> InlineKeyboardMarkup:
    fmt_buttons = []
    for fmt in SUPPORTED_FORMATS:
        label = f"✓ {fmt.upper()}" if fmt == original_fmt.lower() else fmt.upper()
        fmt_buttons.append(InlineKeyboardButton(label, callback_data=f"fmt:{idx}:{fmt}"))
    return InlineKeyboardMarkup([
        fmt_buttons,
        [InlineKeyboardButton("❌ Cancelar", callback_data="cancel_dl")],
    ])


async def handle_download_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show format selection when [Descargar] is tapped."""
    callback = update.callback_query
    await callback.answer()

    chat_id = update.effective_chat.id
    idx = int(callback.data.split(":")[1])
    books = _cache.get(chat_id, [])

    if idx >= len(books):
        await callback.answer("Sesión expirada. Haz una nueva búsqueda.", show_alert=True)
        return

    book = books[idx]
    original_fmt = (book.get("extension") or "epub").lower()

    await context.bot.send_message(
        chat_id=chat_id,
        text=f"📥 *{_safe(book['title'])}*\n\nElige el formato de descarga:\n_(✓ = formato original, sin conversión)_",
        reply_markup=_format_keyboard(idx, original_fmt),
        parse_mode="Markdown",
    )


# ── Download + convert ────────────────────────────────────────────────────────

async def handle_fmt_download(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    callback = update.callback_query
    await callback.answer()

    parts = callback.data.split(":")
    idx, fmt = int(parts[1]), parts[2]
    chat_id = update.effective_chat.id
    books = _cache.get(chat_id, [])

    if idx >= len(books):
        await callback.answer("Sesión expirada. Haz una nueva búsqueda.", show_alert=True)
        return

    book = books[idx]
    title = _safe(book["title"])

    await callback.edit_message_text(f"⏳ Descargando *{title}*…", parse_mode="Markdown")

    loop = asyncio.get_event_loop()
    path: Path | None = await loop.run_in_executor(None, download_book, book)

    if path is None:
        await callback.edit_message_text(
            f"❌ No se pudo descargar *{title}*.", parse_mode="Markdown"
        )
        return

    # Convert if format differs
    original_fmt = path.suffix.lstrip(".").lower()
    if original_fmt != fmt:
        await callback.edit_message_text(
            f"⚙️ Convirtiendo a *{fmt.upper()}*…", parse_mode="Markdown"
        )
        converted = await loop.run_in_executor(None, convert, path, fmt)
        if converted is None:
            path.unlink(missing_ok=True)
            await callback.edit_message_text(
                f"❌ Error al convertir a {fmt.upper()}.", parse_mode="Markdown"
            )
            return
        path = converted

    size_mb = path.stat().st_size / (1024 * 1024)
    if size_mb > TELEGRAM_MAX_FILE_MB:
        path.unlink(missing_ok=True)
        await callback.edit_message_text(
            f"⚠️ El archivo pesa {size_mb:.1f} MB (límite Telegram: 50 MB)."
        )
        return

    await callback.edit_message_text(f"📤 Enviando *{title}*…", parse_mode="Markdown")

    try:
        caption = f"📖 *{title}*"
        if book.get("author"):
            caption += f"\n✍️ {_safe(book['author'])}"
        caption += f"\n📁 {fmt.upper()}"

        with open(path, "rb") as f:
            await context.bot.send_document(
                chat_id=chat_id,
                document=f,
                filename=path.name,
                caption=caption,
                parse_mode="Markdown",
            )
        await callback.edit_message_text(
            f"✅ *{title}* enviado en {fmt.upper()}.", parse_mode="Markdown"
        )
    except Exception as e:
        logger.error("Send error: %s", e)
        await callback.edit_message_text("❌ Error al enviar el archivo.")
    finally:
        path.unlink(missing_ok=True)


async def handle_cancel_download(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    callback = update.callback_query
    await callback.answer()
    try:
        await callback.message.delete()
    except Exception:
        pass


# ── Send (Phase 3 placeholder) ────────────────────────────────────────────────

async def handle_send(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    callback = update.callback_query
    await callback.answer("📨 Envío a Kindle — próximamente.", show_alert=True)


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
    app.add_handler(CallbackQueryHandler(handle_detail,          pattern=r"^d:\d+$"))
    app.add_handler(CallbackQueryHandler(handle_download_menu,   pattern=r"^dl:\d+$"))
    app.add_handler(CallbackQueryHandler(handle_fmt_download,    pattern=r"^fmt:\d+:\w+$"))
    app.add_handler(CallbackQueryHandler(handle_cancel_download, pattern=r"^cancel_dl$"))
    app.add_handler(CallbackQueryHandler(handle_send,            pattern=r"^send:\d+$"))
    app.add_handler(CallbackQueryHandler(handle_back,            pattern=r"^back$"))

    logger.info("BookFinder bot started.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
