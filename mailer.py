"""
BookFinder — SMTP mailer

Sends ebook files to a Kindle email address via SMTP (e.g. Gmail App Password).
Amazon will deliver the file to the Kindle linked to that @kindle.com address.
"""

import logging
import smtplib
import time
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from config import SMTP_FROM, SMTP_HOST, SMTP_PASS, SMTP_PORT, SMTP_USER

logger = logging.getLogger(__name__)

KINDLE_MAX_BYTES = 50 * 1024 * 1024  # Amazon's 50 MB email limit

# Retry delays in seconds between SMTP attempts (transient failures only)
_RETRY_DELAYS = [10, 30]

# Non-retryable SMTP errors (permanent failures)
_PERMANENT_ERRORS = (smtplib.SMTPAuthenticationError, smtplib.SMTPRecipientsRefused)


def _build_message(sender: str, kindle_email: str, title: str, file_path: Path) -> MIMEMultipart:
    msg = MIMEMultipart()
    msg["From"] = sender
    msg["To"] = kindle_email
    msg["Subject"] = title
    msg.attach(MIMEText("Sent via BookFinder."))

    ext = file_path.suffix.lower().lstrip(".")
    # Use correct MIME subtype for EPUB so Amazon identifies the format properly
    mime_subtype = "epub+zip" if ext == "epub" else "octet-stream"

    with open(file_path, "rb") as f:
        attachment = MIMEApplication(f.read(), _subtype=mime_subtype, Name=file_path.name)
    attachment["Content-Disposition"] = f'attachment; filename="{file_path.name}"'
    msg.attach(attachment)
    return msg


def send_to_kindle(kindle_email: str, file_path: Path, title: str) -> tuple[str | None, dict]:
    """
    Send file_path as an email attachment to kindle_email.

    Returns (error_str | None, info_dict).
    error_str is None on success; info_dict always contains sender, size_mb,
    filename, mime, and send_attempts.
    The sender (SMTP_FROM) must be in the recipient's Amazon approved email list.
    Retries up to 2 times on transient SMTP/connection errors.
    """
    sender = SMTP_FROM or SMTP_USER or ""
    file_size = file_path.stat().st_size if file_path.exists() else 0
    ext = file_path.suffix.lower().lstrip(".")
    info = {
        "sender": sender,
        "size_mb": round(file_size / 1024 / 1024, 2),
        "filename": file_path.name,
        "mime": f"application/{'epub+zip' if ext == 'epub' else 'octet-stream'}",
        "send_attempts": 0,
    }

    if not all([SMTP_HOST, SMTP_USER, SMTP_PASS]):
        return "SMTP no configurado en el servidor (faltan SMTP_HOST, SMTP_USER o SMTP_PASS).", info

    if file_size > KINDLE_MAX_BYTES:
        return f"Archivo demasiado grande ({info['size_mb']} MB). Amazon acepta máximo 50 MB.", info

    msg = _build_message(sender, kindle_email, title, file_path)

    last_error: str = "Error desconocido."
    attempts = 1 + len(_RETRY_DELAYS)

    for attempt in range(attempts):
        if attempt > 0:
            delay = _RETRY_DELAYS[attempt - 1]
            logger.info("SMTP retry %d/%d after %ds…", attempt, len(_RETRY_DELAYS), delay)
            time.sleep(delay)

        info["send_attempts"] = attempt + 1
        try:
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as smtp:
                smtp.ehlo()
                smtp.starttls()
                smtp.login(SMTP_USER, SMTP_PASS)
                smtp.send_message(msg)
            logger.info(
                "Sent '%s' (%.2f MB, %s) → %s attempt=%d",
                file_path.name, info["size_mb"], info["mime"], kindle_email, attempt + 1,
            )
            return None, info

        except _PERMANENT_ERRORS as e:
            if isinstance(e, smtplib.SMTPAuthenticationError):
                return "Autenticación SMTP fallida — revisa SMTP_USER y SMTP_PASS en el servidor.", info
            return f"Dirección Kindle rechazada por el servidor: `{kindle_email}`", info

        except smtplib.SMTPException as e:
            last_error = f"Error SMTP: {e}"
            logger.warning("SMTP error attempt %d: %s", attempt + 1, e)

        except OSError as e:
            last_error = f"No se pudo conectar al servidor SMTP ({SMTP_HOST}:{SMTP_PORT}): {e}"
            logger.warning("Connection error attempt %d: %s", attempt + 1, e)

    return last_error, info
