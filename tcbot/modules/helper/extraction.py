# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Studio

"""Target extraction helpers: ResolvedTarget and extract_target()."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from tcbot import database as db

if TYPE_CHECKING:
    from telegram import Bot, Chat, Message, Update, User

log = logging.getLogger(__name__)

# * Telegram lookups are wrapped in wait_for so a stalled API call never blocks
# * the user-facing reply. Three seconds is the standard project-wide budget.
_GET_CHAT_TIMEOUT = 3.0


async def _safe_get_chat(bot: Bot, ident: str | int) -> Chat | None:
    """Call ``bot.get_chat`` with a bounded timeout; returns ``None`` on failure."""
    try:
        return await asyncio.wait_for(bot.get_chat(ident), timeout=_GET_CHAT_TIMEOUT)
    except Exception as exc:
        log.debug("get_chat(%s) failed: %s", ident, exc)
        return None


# ──────────────────────── Target resolution ─────────────────────── #


@dataclass
class ResolvedTarget:
    """A resolved Telegram user target with a guaranteed display name."""

    id: int
    first_name: str | None
    username: str | None = None
    raw: object = field(default=None, compare=False, repr=False)

    def __post_init__(self) -> None:
        """Fall back to a string representation of id when first_name is empty."""
        if not self.first_name:
            self.first_name = str(self.id)


async def _best_name(uid: int, *primary: str | None) -> str:
    """Pick the first non-empty/non-numeric primary name; fall back to cache, then 'User <uid>'."""
    for cand in primary:
        if cand and not cand.lstrip("-").isdigit():
            return cand
    # * Try the member cache before resorting to "User <id>".
    cached = await db.users_cache.get_first_name(uid, "")
    if cached and not cached.lstrip("-").isdigit():
        return cached
    return f"User {uid}"


async def extract_target(
    update: Update,
    args: list[str],
    bot: Bot | None = None,
) -> tuple[int, str] | tuple[None, None]:
    """Return (user_id, first_name) resolved from reply, args, entity, or mention.

    Priority order:
    1. Reply (most common use case)
    2. Args with full info (numeric ID or @username)
    3. Args with partial info (search users_cache by name)
    4. Text mention entity
    5. @Mention entity

    The returned name is always a human-readable string. When Telegram returns
    no first_name and the member cache has no entry, falls back to ``User <uid>``
    rather than a bare numeric ID so log messages and mention links stay legible.
    """
    msg: Message = update.effective_message

    # * Priority 1: Reply target (most common use case)
    if msg.reply_to_message and msg.reply_to_message.from_user:
        u: User = msg.reply_to_message.from_user
        return u.id, u.first_name or await _best_name(u.id)

    # * Priority 2 & 3: Explicit args (full ID/username or partial name search)
    if args:
        arg = args[0].lstrip("@")

        # * Priority 2a: Numeric ID
        if arg.lstrip("-").isdigit():
            uid = int(arg)
            chat_first: str | None = None
            chat_username: str | None = None
            if bot:
                chat = await _safe_get_chat(bot, uid)
                if chat is not None:
                    chat_first = chat.first_name
                    chat_username = chat.username
            return uid, await _best_name(uid, chat_first, chat_username)

        # * Priority 2b: @username lookup
        if bot and arg:
            chat = await _safe_get_chat(bot, f"@{arg}")
            if chat is not None:
                return chat.id, await _best_name(
                    chat.id, chat.first_name, chat.username, arg
                )

        # * Priority 3: Partial name search in users_cache
        if arg:
            all_users = await db.users_cache.all_users()
            needle = arg.lower()
            for user in all_users:
                fname = (user.get("first_name") or "").lower()
                uname = (user.get("username") or "").lower()
                if needle in fname or needle in uname:
                    uid = user.get("user_id")
                    if uid:
                        return uid, user.get("first_name") or await _best_name(uid)

    # * Priority 4: Text mention entity
    for ent in msg.entities or []:
        if ent.type == "text_mention" and ent.user:
            u = ent.user
            return u.id, u.first_name or await _best_name(u.id)

    # * Priority 5: @Mention entity
    if bot:
        text = msg.text or ""
        for ent in msg.entities or []:
            if ent.type == "mention":
                uname = text[ent.offset + 1 : ent.offset + ent.length]
                chat = await _safe_get_chat(bot, f"@{uname}")
                if chat is not None:
                    return chat.id, await _best_name(chat.id, chat.first_name, uname)

    return None, None
