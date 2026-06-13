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

# * Telegram's pseudo-user that represents an anonymous group admin.
# * Its user_id is fixed and well-known. We must skip it as a reply target
# * because acting on it would attempt to ban/kick/mute the bot placeholder,
# * not the real human behind the anonymous admin title.
_ANONYMOUS_BOT_ID = 1087968824

# * Telegram's official service / system account ID.
_TELEGRAM_USER_ID = 777000

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
    """Pick the first non-empty/non-numeric primary name; fall back to cache, then str(uid).

    Returns the raw numeric ID string rather than a decorated ``User <id>``
    form so that callers using ``user_ref()`` or the ``mention() - code(id)``
    pattern can detect a numeric fallback and avoid displaying the ID twice.
    """
    for cand in primary:
        if cand and not cand.lstrip("-").isdigit():
            return cand
    # * Try the member cache before resorting to a bare numeric ID.
    cached = await db.users_cache.get_first_name(uid, "")
    if cached and not cached.lstrip("-").isdigit():
        return cached
    return str(uid)


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
    # * Skip GroupAnonymousBot (id 1087968824): it is a Telegram pseudo-user
    # * that appears as `from_user` when an anonymous admin sends a message.
    # * Targeting it would attempt to act on the placeholder, not a real user.
    # * Similarly skip the Telegram service account (777000) and channel posts.
    if msg.reply_to_message:
        target_msg = msg.reply_to_message
        if target_msg.from_user:
            u: User = target_msg.from_user
            if u.id not in (_ANONYMOUS_BOT_ID, _TELEGRAM_USER_ID):
                return u.id, u.first_name or await _best_name(u.id)

        if target_msg.sender_chat:
            c: Chat = target_msg.sender_chat
            return c.id, c.title or await _best_name(c.id)

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
        # * Uses a server-side regex query capped at 5 results; avoids loading
        # * the entire user cache into Python for a linear scan.
        if arg:
            matches = await db.users_cache.search_by_name(arg)
            if matches:
                user = matches[0]
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
