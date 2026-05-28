# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""Telegram deep-link builders (chat/message links and bot deep links)."""

from __future__ import annotations


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


def appeal_deep_link(bot_username: str, ban_id: str) -> str:
    return f"https://t.me/{bot_username}?start=appeal_{ban_id}"
