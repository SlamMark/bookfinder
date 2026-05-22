"""
BookFinder — Per-user settings

Stored in data/user_settings.json (persisted via Docker volume).
"""

import json
from pathlib import Path

_SETTINGS_FILE = Path(__file__).parent / "data" / "user_settings.json"


def _load() -> dict:
    if not _SETTINGS_FILE.exists():
        return {}
    try:
        return json.loads(_SETTINGS_FILE.read_text())
    except Exception:
        return {}


def _save(data: dict) -> None:
    _SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    _SETTINGS_FILE.write_text(json.dumps(data, indent=2))


def get(chat_id: int) -> dict:
    return _load().get(str(chat_id), {})


def set_kindle_email(chat_id: int, email: str) -> None:
    data = _load()
    data.setdefault(str(chat_id), {})["kindle_email"] = email
    _save(data)


def set_default_format(chat_id: int, fmt: str) -> None:
    data = _load()
    data.setdefault(str(chat_id), {})["default_format"] = fmt
    _save(data)


def get_kindle_email(chat_id: int) -> str | None:
    return get(chat_id).get("kindle_email")


def get_default_format(chat_id: int) -> str | None:
    return get(chat_id).get("default_format")


def set_search_source(chat_id: int, source: str) -> None:
    """source: 'both' | 'zlibrary' | 'libgen'"""
    data = _load()
    data.setdefault(str(chat_id), {})["search_source"] = source
    _save(data)


def get_search_source(chat_id: int) -> str:
    return get(chat_id).get("search_source", "both")


def get_status(chat_id: int) -> str | None:
    """Returns 'approved', 'pending', 'rejected', or None if unknown user."""
    return get(chat_id).get("status")


def register_user(chat_id: int, name: str, username: str | None) -> None:
    data = _load()
    entry = data.setdefault(str(chat_id), {})
    entry["status"]   = "pending"
    entry["name"]     = name
    entry["username"] = username or ""
    _save(data)


def set_status(chat_id: int, status: str) -> None:
    data = _load()
    data.setdefault(str(chat_id), {})["status"] = status
    _save(data)
