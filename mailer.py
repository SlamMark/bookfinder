"""
BookFinder — SMTP mailer

Sends ebook files to a Kindle email address via SMTP (e.g. Gmail App Password).
Amazon will deliver the file to the Kindle linked to that @kindle.com address.
"""

import logging
import smtplib
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from config import SMTP_FROM, SMTP_HOST, SMTP_PASS, SMTP_PORT, SMTP_USER

logger = logging.getLogger(__name__)


def send_to_kindle(kindle_email: str, file_path: Path, title: str) -> bool:
    """
    Send file_path as an email attachment to kindle_email.

    Returns True on success, False on failure.
    The sender (SMTP_FROM) must be in the recipient's Amazon approved email list.
    """
    if not all([SMTP_HOST, SMTP_USER, SMTP_PASS]):
        logger.error("SMTP not configured (SMTP_HOST/SMTP_USER/SMTP_PASS missing).")
        return False

    msg = MIMEMultipart()
    msg["From"] = SMTP_FROM or SMTP_USER
    msg["To"] = kindle_email
    msg["Subject"] = title

    msg.attach(MIMEText("Sent via BookFinder."))

    with open(file_path, "rb") as f:
        attachment = MIMEApplication(f.read(), Name=file_path.name)
    attachment["Content-Disposition"] = f'attachment; filename="{file_path.name}"'
    msg.attach(attachment)

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.login(SMTP_USER, SMTP_PASS)
            smtp.send_message(msg)
        logger.info("Sent '%s' to %s", file_path.name, kindle_email)
        return True
    except Exception as e:
        logger.error("SMTP error: %s", e)
        return False
