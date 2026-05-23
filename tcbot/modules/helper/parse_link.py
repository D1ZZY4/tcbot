# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""Link builders and HTML helpers for Telegram deep links and mentions."""

from __future__ import annotations

import html

def chat_id_to_link_id(chat_id: int) -> str:
    """Strip the -100 supergroup prefix for use in t.me/c/ URLs."""
    s = str(chat_id)
    if s.startswith("-100"):
        return s[4:]
    return s.lstrip("-")


def message_link(chat_id: int, message_id: int, thread_id: int | None = None) -> str:
    cid = chat_id_to_link_id(chat_id)
    if thread_id:
        return f"https://t.me/c/{cid}/{message_id}?thread={thread_id}"
    return f"https://t.me/c/{cid}/{message_id}"


def topic_link(chat_id: int, message_id: int, thread_id: int) -> str:
    """Build a t.me/c/ deep-link to a specific message inside a topic thread."""
    return message_link(chat_id, message_id, thread_id)


def appeal_deep_link(bot_username: str, ban_id: str) -> str:
    return f"https://t.me/{bot_username}?start=appeal_{ban_id}"


## ── HTML helpers ───────────────────────────────────────────────────────────

def user_link(user_id: int, name: str) -> str:
    """HTML mention link. Falls back to str(user_id) when name is blank."""
    display = html.escape(str(name)) if name else str(user_id)
    return f'<a href="tg://user?id={user_id}">{display}</a>'


def safe_first_name(obj: object) -> str:
    """Extract a display name from a Telegram User/Chat-like object.

    Priority: first_name → title → str(id) → "Unknown".
    """
    first = getattr(obj, "first_name", None)
    if first:
        return str(first)
    title = getattr(obj, "title", None)
    if title:
        return str(title)
    uid = getattr(obj, "id", None)
    if uid is not None:
        return str(uid)
    return "Unknown"
