#!/usr/bin/env python3
"""
BookFinder — Telegram Bot (Phase 2)

Flow:
  User sends text → bot searches Z-Library + Libgen → inline buttons with results
  User taps a button → bot downloads the book and sends the file to the chat
"""

import logging
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

from config import TELEGRAM_TOKEN, MAX_RESULTS, BOT_MAX_RESULTS
from downloader import download_book
from searcher_libgen import search_libgen
from searcher_zlib import search_zlibrary

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Per-chat results cache: {chat_id: [book_dict, ...]}
_cache: dict[int, list[dict]] = {}

TELEGRAM_MAX_FILE_MB = 50


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "📚 *BookFinder*\n\n"
        "Escríbeme el título de un libro y te busco resultados en Z-Library y Libgen.\n\n"
        "Pulsa un resultado para descargarlo y recibirlo aquí.",
        parse_mode="Markdown",
    )


async def handle_search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.message.text.strip()
    chat_id = update.effective_chat.id

    msg = await update.message.reply_text(
        f"🔍 Buscando *{query}*…", parse_mode="Markdown"
    )

    results: list[dict] = []

    # Z-Library first
    try:
        zlib = search_zlibrary(query, max_results=BOT_MAX_RESULTS)
        results.extend(zlib)
    except Exception as e:
        logger.warning("Z-Library search error: %s", e)

    # Libgen as fallback if not enough results
    if len(results) < BOT_MAX_RESULTS:
        try:
            libgen = search_libgen(
                query, max_results=BOT_MAX_RESULTS - len(results)
            )
            results.extend(libgen)
        except Exception as e:
            logger.warning("Libgen search error: %s", e)

    if not results:
        await msg.edit_text("❌ No encontré nada. Prueba con otro título.")
        return

    _cache[chat_id] = results[:BOT_MAX_RESULTS]

    buttons = []
    for i, book in enumerate(_cache[chat_id]):
        icon = "🟡" if book["source"] == "zlibrary" else "🟢"
        title = book["title"][:40].strip()
        ext = book["extension"].upper() if book["extension"] else "?"
        size = book["size"] or ""
        label = f"{icon} {title} [{ext}] {size}".strip()
        buttons.append([InlineKeyboardButton(label, callback_data=str(i))])

    await msg.edit_text(
        f"📚 *{query}* — elige un resultado:",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="Markdown",
    )


async def handle_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    callback = update.callback_query
    await callback.answer()

    chat_id = update.effective_chat.id
    idx = int(callback.data)
    books = _cache.get(chat_id, [])

    if idx >= len(books):
        await callback.edit_message_text("❌ Selección inválida.")
        return

    book = books[idx]
    title = book["title"]

    await callback.edit_message_text(
        f"⏳ Descargando *{title}*…", parse_mode="Markdown"
    )

    path: Path | None = download_book(book)

    if path is None:
        await callback.edit_message_text(
            f"❌ No se pudo descargar *{title}*. Prueba con otro resultado.",
            parse_mode="Markdown",
        )
        return

    size_mb = path.stat().st_size / (1024 * 1024)
    if size_mb > TELEGRAM_MAX_FILE_MB:
        await callback.edit_message_text(
            f"⚠️ El archivo pesa {size_mb:.1f} MB, demasiado grande para Telegram (límite 50 MB).",
        )
        path.unlink(missing_ok=True)
        return

    await callback.edit_message_text(
        f"📤 Enviando *{title}*…", parse_mode="Markdown"
    )

    try:
        caption = f"📖 *{title}*"
        if book.get("author"):
            caption += f"\n👤 {book['author']}"

        with open(path, "rb") as f:
            await context.bot.send_document(
                chat_id=chat_id,
                document=f,
                filename=path.name,
                caption=caption,
                parse_mode="Markdown",
            )

        await callback.edit_message_text(
            f"✅ *{title}* enviado.", parse_mode="Markdown"
        )
    except Exception as e:
        logger.error("Error sending file: %s", e)
        await callback.edit_message_text("❌ Error al enviar el archivo.")
    finally:
        path.unlink(missing_ok=True)


def main() -> None:
    if not TELEGRAM_TOKEN:
        raise RuntimeError("TELEGRAM_TOKEN is not set in .env")

    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_search))
    app.add_handler(CallbackQueryHandler(handle_button))

    logger.info("BookFinder bot started.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
