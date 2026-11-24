# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Telegram link builders and community link resolution.

Deep links and public community links share one owner here: both turn chat
ids or bot data into a URL, so they belong together. Community links are
cached because a chat username or invite link rarely changes mid-process.
"""

from __future__ import annotations

import asyncio
import time

from pyrogram import Client

from tcbot.utils.logger import get_logger
from tcbot.utils.transport import TELEGRAM_LOOKUP_TIMEOUT

log = get_logger(__name__)

_CACHE_TTL_S: float = 300.0
# * One lookup budget for every Telegram get_chat/get_chat_member call.
_LOOKUP_TIMEOUT_S: float = TELEGRAM_LOOKUP_TIMEOUT

_cache: dict[int, tuple[str, float]] = {}
_locks: dict[int, asyncio.Lock] = {}


def chat_id_to_link_id(chat_id: int) -> str:
    """Strip the -100 supergroup prefix for use in t.me/c/ URLs."""
    s = str(chat_id)
    if s.startswith("-100"):
        return s[4:]
    return s.lstrip("-")


def message_link(chat_id: int, message_id: int, thread_id: int | None = None) -> str:
    """Build a ``t.me/c/`` deep link to a specific message, optionally in a thread."""
    cid = chat_id_to_link_id(chat_id)
    if thread_id:
        return f"https://t.me/c/{cid}/{message_id}?thread={thread_id}"
    return f"https://t.me/c/{cid}/{message_id}"


def appeal_deep_link(bot_username: str, ban_id: str) -> str:
    """Return a bot deep link, or an empty string when the username is unknown."""
    if not bot_username:
        return ""
    return f"https://t.me/{bot_username}?start=appeal_{ban_id}"


def forget(chat_id: int) -> None:
    """Drop the cached community link of one chat."""
    _cache.pop(chat_id, None)


def clear() -> None:
    """Drop every cached community link."""
    _cache.clear()


def _cached(chat_id: int) -> str | None:
    """Return an unexpired cached link, removing an expired entry."""
    entry = _cache.get(chat_id)
    if entry is None:
        return None
    value, expires_at = entry
    if expires_at <= time.monotonic():
        _cache.pop(chat_id, None)
        return None
    return value


async def resolve(bot: Client, chat_id: int) -> str | None:
    """Return a public link for *chat_id*, or None when Telegram has none."""
    if chat_id == 0:
        return None
    cached = _cached(chat_id)
    if cached is not None:
        return cached
    lock = _locks.setdefault(chat_id, asyncio.Lock())
    async with lock:
        cached = _cached(chat_id)
        if cached is not None:
            return cached
        try:
            async with asyncio.timeout(_LOOKUP_TIMEOUT_S):
                chat = await bot.get_chat(chat_id)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.debug("Community link lookup failed for %d: %s", chat_id, exc)
            return None
        username = getattr(chat, "username", None)
        value = (
            f"https://t.me/{username}"
            if username
            else getattr(chat, "invite_link", None)
        )
        if not isinstance(value, str) or not value:
            return None
        _cache[chat_id] = (value, time.monotonic() + _CACHE_TTL_S)
        return value


async def display(bot: Client, chat_id: int) -> str:
    """Return a public link, falling back to the numeric chat id."""
    return await resolve(bot, chat_id) or str(chat_id)


__all__ = [
    "appeal_deep_link",
    "chat_id_to_link_id",
    "clear",
    "display",
    "forget",
    "message_link",
    "resolve",
]
