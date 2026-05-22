"""
BookFinder — Calibre converter

Converts ebooks using Calibre CLI (ebook-convert).
  --enable-heuristics  fixes common HTML/formatting issues
  Cover is preserved automatically from the source file.
"""

import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

SUPPORTED_FORMATS = ["epub", "mobi", "azw3", "pdf"]

KINDLE_EMAIL_FORMATS = ["epub", "mobi", "azw3", "pdf"]


def convert(src: Path, target_format: str) -> Path | None:
    """
    Convert src to target_format using Calibre.

    Returns the converted Path on success, or None on failure.
    If src is already in target_format, returns src unchanged (no conversion).
    On successful conversion the original file is deleted.
    """
    src_fmt = src.suffix.lstrip(".").lower()
    target_fmt = target_format.lower()

    if src_fmt == target_fmt:
        return src

    out = src.with_suffix(f".{target_fmt}")

    logger.info("Converting %s → %s", src.name, out.name)
    try:
        result = subprocess.run(
            ["ebook-convert", str(src), str(out), "--enable-heuristics"],
            capture_output=True,
            timeout=300,
        )
        if result.returncode != 0:
            logger.error("Calibre stderr: %s", result.stderr.decode(errors="replace"))
            return None

        src.unlink(missing_ok=True)
        return out

    except FileNotFoundError:
        logger.error("ebook-convert not found — is Calibre installed?")
        return None
    except subprocess.TimeoutExpired:
        logger.error("Calibre conversion timed out.")
        return None
    except Exception as e:
        logger.error("Conversion error: %s", e)
        return None
