# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""Time formatting, HTML link builders, and topic-link helpers."""
from __future__ import annotations

from datetime import datetime, timezone
from html import escape
from typing import Any


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def fmt_dt(dt: datetime) -> str:
    return dt.strftime("%d-%m-%Y | %H:%M")


def fmt_now() -> str:
    return fmt_dt(utcnow())


def user_link(user_id: int, name: str) -> str:
    return f'<a href="tg://user?id={user_id}">{escape(name or str(user_id))}</a>'


def chat_id_to_link_id(chat_id: int) -> str:
    """Convert a -100xxxxx supergroup/channel id to its t.me/c URL numeric segment."""
    s = str(abs(chat_id))
    if s.startswith("100"):
        return s[3:]
    return s


def topic_link(chat_id: int, message_id: int, thread_id: int) -> str:
    return f"https://t.me/c/{chat_id_to_link_id(chat_id)}/{message_id}?thread={thread_id}"


def safe_first_name(obj: Any) -> str:
    """Best-effort display name for a Telegram ``User`` / ``Chat``-like object.

    Order: ``first_name`` -> ``title`` -> ``@username`` -> numeric ``id``
    -> ``"Unknown"``. The ``@username`` step keeps log lines and replies
    readable for users who only set a username (no ``first_name``) instead
    of falling straight through to a bare numeric id.
    """
    name = getattr(obj, "first_name", None) or getattr(obj, "title", None)
    if name:
        return name
    username = getattr(obj, "username", None)
    if username:
        return f"@{username}"
    obj_id = getattr(obj, "id", None)
    return str(obj_id) if obj_id is not None else "Unknown"
