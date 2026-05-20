#!/usr/bin/env python3
"""
BookFinder — Telegram Bot

Commands:
  /start         — welcome
  /setkindle     — set your Kindle email  (e.g. /setkindle xxxx@kindle.com)
  /setformat     — set your default download/send format

Flow:
  Text message → search → list → detail view
  [Descargar]  → format selection → download + convert → Telegram file
  [Enviar]     → format selection → download + convert → email to Kindle
  [Volver]     → back to list
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

from config import TELEGRAM_TOKEN, TELEGRAM_ADMIN_ID, BOT_MAX_RESULTS
from converter import KINDLE_EMAIL_FORMATS, SUPPORTED_FORMATS, convert
from downloader import download_book
from mailer import send_to_kindle
from searcher_libgen import search_libgen
from searcher_zlib import get_book_details, search_zlibrary
from user_settings import (
    get,
    get_default_format,
    get_kindle_email,
    get_status,
    register_user,
    set_default_format,
    set_kindle_email,
    set_status,
)

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

_cache: dict[int, list[dict]] = {}
TELEGRAM_MAX_FILE_MB = 50


def _safe(text) -> str:
    return re.sub(r"[*_`\[\]]", "", str(text or "")).strip()


def _is_admin(chat_id: int) -> bool:
    return TELEGRAM_ADMIN_ID and chat_id == TELEGRAM_ADMIN_ID


# ── Access control ────────────────────────────────────────────────────────────

async def _check_access(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    Returns True if the user can proceed.
    Handles registration and notifies admin of new requests.
    """
    user = update.effective_user
    chat_id = user.id

    if _is_admin(chat_id):
        return True

    status = get_status(chat_id)

    if status == "approved":
        return True

    if status == "pending":
        await update.effective_message.reply_text(
            "⏳ Tu solicitud de acceso está pendiente de aprobación."
        )
        return False

    if status == "rejected":
        await update.effective_message.reply_text(
            "❌ Tu solicitud de acceso fue rechazada."
        )
        return False

    # New user — register and notify admin
    name = user.full_name or "Desconocido"
    register_user(chat_id, name, user.username)

    await update.effective_message.reply_text(
        "👋 Hola! Para usar BookFinder necesitas aprobación del administrador.\n\n"
        "Tu solicitud ha sido enviada. Te avisaré cuando sea aprobada."
    )

    if TELEGRAM_ADMIN_ID:
        username_str = f"@{user.username}" if user.username else "sin username"
        await context.bot.send_message(
            chat_id=TELEGRAM_ADMIN_ID,
            text=f"🔔 *Nueva solicitud de acceso*\n\n"
                 f"👤 *{_safe(name)}* ({username_str})\n"
                 f"🆔 `{chat_id}`",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("✅ Aprobar", callback_data=f"approve:{chat_id}"),
                InlineKeyboardButton("❌ Rechazar", callback_data=f"reject:{chat_id}"),
            ]]),
            parse_mode="Markdown",
        )

    return False


# ── Commands ──────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "📚 *BookFinder*\n\n"
        "Escríbeme el título de un libro para buscarlo.\n\n"
        "*Comandos:*\n"
        "/setkindle `email@kindle.com` — guarda tu email de Kindle\n"
        "/setformat — elige tu formato por defecto",
        parse_mode="Markdown",
    )


async def cmd_myid(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    await update.message.reply_text(f"Tu chat ID es: `{chat_id}`", parse_mode="Markdown")


async def cmd_setkindle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    args = context.args

    if not args:
        current = get_kindle_email(chat_id)
        msg = f"📧 Tu Kindle email actual: `{current}`" if current else "📧 No tienes Kindle email configurado."
        await update.message.reply_text(
            msg + "\n\nUso: `/setkindle tu@kindle.com`",
            parse_mode="Markdown",
        )
        return

    email = args[0].strip()
    if "@" not in email:
        await update.message.reply_text("❌ Email inválido. Ejemplo: `/setkindle xxxx@kindle.com`", parse_mode="Markdown")
        return

    set_kindle_email(chat_id, email)
    await update.message.reply_text(
        f"✅ Kindle email guardado: `{email}`\n\n"
        f"Recuerda añadir `{email.split('@')[0] if 'SMTP_FROM' not in email else ''}` "
        f"a tu lista de emails aprobados en Amazon:\n"
        f"Amazon → Manage Your Content → Preferences → Approved Personal Document E-mail List",
        parse_mode="Markdown",
    )


async def cmd_setformat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    current = get_default_format(chat_id)

    buttons = []
    row = []
    for fmt in SUPPORTED_FORMATS:
        label = f"✓ {fmt.upper()}" if fmt == (current or "") else fmt.upper()
        row.append(InlineKeyboardButton(label, callback_data=f"setfmt:{fmt}"))
    buttons.append(row)

    msg = f"📁 Formato actual: *{current.upper()}*\n\nElige tu formato por defecto:" if current else "📁 Elige tu formato por defecto:"
    await update.message.reply_text(
        msg,
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="Markdown",
    )


async def handle_setfmt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    callback = update.callback_query
    await callback.answer()
    chat_id = update.effective_chat.id
    fmt = callback.data.split(":")[1]
    set_default_format(chat_id, fmt)
    await callback.edit_message_text(f"✅ Formato por defecto guardado: *{fmt.upper()}*", parse_mode="Markdown")


# ── Approve / Reject ──────────────────────────────────────────────────────────

async def handle_approve(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    callback = update.callback_query
    await callback.answer()

    if not _is_admin(update.effective_chat.id):
        return

    user_chat_id = int(callback.data.split(":")[1])
    set_status(user_chat_id, "approved")

    user_info = get(user_chat_id)
    name = _safe(user_info.get("name", "Usuario"))

    await callback.edit_message_text(f"✅ *{name}* aprobado.", parse_mode="Markdown")
    try:
        await context.bot.send_message(
            chat_id=user_chat_id,
            text="✅ Tu solicitud ha sido aprobada. Ya puedes usar BookFinder.\n\nEscribe el título de un libro para empezar.",
        )
    except Exception:
        pass


async def handle_reject(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    callback = update.callback_query
    await callback.answer()

    if not _is_admin(update.effective_chat.id):
        return

    user_chat_id = int(callback.data.split(":")[1])
    set_status(user_chat_id, "rejected")

    user_info = get(user_chat_id)
    name = _safe(user_info.get("name", "Usuario"))

    await callback.edit_message_text(f"❌ *{name}* rechazado.", parse_mode="Markdown")
    try:
        await context.bot.send_message(
            chat_id=user_chat_id,
            text="❌ Tu solicitud de acceso ha sido rechazada.",
        )
    except Exception:
        pass


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
    if not await _check_access(update, context):
        return

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
            results.extend(search_libgen(query, max_results=BOT_MAX_RESULTS - len(results)))
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
    row("📅", "Año",          "year",        fallback=book.get("year"))
    row("🌍", "Idioma",       "language",    fallback=book.get("language"))
    row("📚", "Serie",        "series")
    row("🏢", "Editorial",    "publisher",   fallback=book.get("publisher"))

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
    if not await _check_access(update, context):
        await update.callback_query.answer()
        return

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


# ── Format selection (shared for download and send) ───────────────────────────

def _format_keyboard(idx: int, action: str, original_fmt: str, default_fmt: str | None) -> InlineKeyboardMarkup:
    """
    action: 'dl' for download, 'snd' for send.
    Marks default format with ✓, original book format with (original).
    Send uses KINDLE_EMAIL_FORMATS only (Amazon dropped MOBI support in 2022).
    """
    formats = KINDLE_EMAIL_FORMATS if action == "snd" else SUPPORTED_FORMATS
    buttons = []
    for fmt in formats:
        parts = []
        if fmt == (default_fmt or "").lower():
            parts.append("✓")
        label = f"{' '.join(parts)} {fmt.upper()}".strip()
        if fmt == original_fmt.lower() and fmt != (default_fmt or "").lower():
            label += " (original)"
        buttons.append(InlineKeyboardButton(label, callback_data=f"fmt:{action}:{idx}:{fmt}"))

    return InlineKeyboardMarkup([
        buttons,
        [InlineKeyboardButton("❌ Cancelar", callback_data="cancel_fmt")],
    ])


async def _show_format_menu(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    idx: int,
    action: str,          # 'dl' or 'snd'
    action_label: str,    # 'Descargar' or 'Enviar al Kindle'
) -> None:
    callback = update.callback_query
    await callback.answer()

    chat_id = update.effective_chat.id
    books = _cache.get(chat_id, [])

    if idx >= len(books):
        await callback.answer("Sesión expirada. Haz una nueva búsqueda.", show_alert=True)
        return

    book = books[idx]
    original_fmt = (book.get("extension") or "epub").lower()
    default_fmt = get_default_format(chat_id)

    hint = f"✓ = formato por defecto   (original) = formato del archivo"
    await context.bot.send_message(
        chat_id=chat_id,
        text=f"*{action_label}* — elige formato:\n_{hint}_",
        reply_markup=_format_keyboard(idx, action, original_fmt, default_fmt),
        parse_mode="Markdown",
    )


async def handle_download_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    idx = int(update.callback_query.data.split(":")[1])
    await _show_format_menu(update, context, idx, "dl", "Descargar")


async def handle_send_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    idx = int(update.callback_query.data.split(":")[1])
    chat_id = update.effective_chat.id

    if not get_kindle_email(chat_id):
        await update.callback_query.answer(
            "No tienes Kindle email configurado.\nUsa /setkindle tu@kindle.com",
            show_alert=True,
        )
        return

    await _show_format_menu(update, context, idx, "snd", "Enviar al Kindle")


# ── Shared download + convert helper ─────────────────────────────────────────

async def _download_and_convert(
    callback,
    context: ContextTypes.DEFAULT_TYPE,
    book: dict,
    fmt: str,
) -> Path | None:
    """Download book and convert to fmt. Updates callback message with progress."""
    title = _safe(book["title"])
    loop = asyncio.get_event_loop()

    await callback.edit_message_text(f"⏳ Descargando *{title}*…", parse_mode="Markdown")
    path: Path | None = await loop.run_in_executor(None, download_book, book)

    if path is None:
        await callback.edit_message_text(f"❌ No se pudo descargar *{title}*.", parse_mode="Markdown")
        return None

    if path.suffix.lstrip(".").lower() != fmt:
        await callback.edit_message_text(f"⚙️ Convirtiendo a *{fmt.upper()}*…", parse_mode="Markdown")
        converted = await loop.run_in_executor(None, convert, path, fmt)
        if converted is None:
            path.unlink(missing_ok=True)
            await callback.edit_message_text(f"❌ Error al convertir a {fmt.upper()}.", parse_mode="Markdown")
            return None
        path = converted

    return path


# ── Handle format selection ───────────────────────────────────────────────────

async def handle_fmt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    callback = update.callback_query
    await callback.answer()

    _, action, idx_str, fmt = callback.data.split(":")
    idx = int(idx_str)
    chat_id = update.effective_chat.id
    books = _cache.get(chat_id, [])

    if idx >= len(books):
        await callback.answer("Sesión expirada. Haz una nueva búsqueda.", show_alert=True)
        return

    book = books[idx]
    title = _safe(book["title"])

    path = await _download_and_convert(callback, context, book, fmt)
    if path is None:
        return

    if action == "dl":
        # ── Send file to Telegram ──
        size_mb = path.stat().st_size / (1024 * 1024)
        if size_mb > TELEGRAM_MAX_FILE_MB:
            path.unlink(missing_ok=True)
            await callback.edit_message_text(f"⚠️ El archivo pesa {size_mb:.1f} MB (límite Telegram: 50 MB).")
            return

        await callback.edit_message_text(f"📤 Enviando *{title}*…", parse_mode="Markdown")
        try:
            caption = f"📖 *{title}*"
            if book.get("author"):
                caption += f"\n✍️ {_safe(book['author'])}"
            caption += f"\n📁 {fmt.upper()}"
            with open(path, "rb") as f:
                await context.bot.send_document(
                    chat_id=chat_id, document=f, filename=path.name,
                    caption=caption, parse_mode="Markdown",
                )
            await callback.edit_message_text(f"✅ *{title}* enviado en {fmt.upper()}.", parse_mode="Markdown")
        except Exception as e:
            logger.error("Send to Telegram error: %s", e)
            await callback.edit_message_text("❌ Error al enviar el archivo.")
        finally:
            path.unlink(missing_ok=True)

    elif action == "snd":
        # ── Send file by email to Kindle ──
        kindle_email = get_kindle_email(chat_id)
        if not kindle_email:
            path.unlink(missing_ok=True)
            await callback.edit_message_text("❌ No tienes Kindle email configurado. Usa /setkindle.")
            return

        await callback.edit_message_text(f"📨 Enviando al Kindle `{kindle_email}`…", parse_mode="Markdown")
        loop = asyncio.get_event_loop()
        ok = await loop.run_in_executor(None, send_to_kindle, kindle_email, path, title)
        path.unlink(missing_ok=True)

        if ok:
            await callback.edit_message_text(
                f"✅ *{title}* enviado a `{kindle_email}` en {fmt.upper()}.\n\n"
                f"Aparecerá en tu Kindle en unos minutos.",
                parse_mode="Markdown",
            )
        else:
            await callback.edit_message_text(
                "❌ Error al enviar el email. Comprueba la configuración SMTP en el servidor."
            )


async def handle_cancel_fmt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    callback = update.callback_query
    await callback.answer()
    try:
        await callback.message.delete()
    except Exception:
        pass


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

    app.add_handler(CommandHandler("start",     cmd_start))
    app.add_handler(CommandHandler("myid",      cmd_myid))
    app.add_handler(CommandHandler("setkindle", cmd_setkindle))
    app.add_handler(CommandHandler("setformat", cmd_setformat))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_search))

    app.add_handler(CallbackQueryHandler(handle_detail,       pattern=r"^d:\d+$"))
    app.add_handler(CallbackQueryHandler(handle_download_menu, pattern=r"^dl:\d+$"))
    app.add_handler(CallbackQueryHandler(handle_send_menu,    pattern=r"^send:\d+$"))
    app.add_handler(CallbackQueryHandler(handle_fmt,          pattern=r"^fmt:(dl|snd):\d+:\w+$"))
    app.add_handler(CallbackQueryHandler(handle_setfmt,       pattern=r"^setfmt:\w+$"))
    app.add_handler(CallbackQueryHandler(handle_cancel_fmt,   pattern=r"^cancel_fmt$"))
    app.add_handler(CallbackQueryHandler(handle_back,         pattern=r"^back$"))
    app.add_handler(CallbackQueryHandler(handle_approve,      pattern=r"^approve:\d+$"))
    app.add_handler(CallbackQueryHandler(handle_reject,       pattern=r"^reject:\d+$"))

    logger.info("BookFinder bot started.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
