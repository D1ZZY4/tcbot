# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""Resolve a ban target (user_id, first_name) from command context."""
from __future__ import annotations

import logging

from telegram import Bot, Message, Update, User

log = logging.getLogger(__name__)


async def extract_target(
    update: Update,
    args: list[str],
    bot: Bot | None = None,
) -> tuple[int, str] | tuple[None, None]:
    """
    Returns (user_id, first_name) resolved from reply, entity, or args.
    Passes args[0] to bot.get_chat() if bot is provided (handles numeric IDs and usernames).
    Returns (None, None) if no valid target can be resolved.
    """
    msg: Message = update.effective_message

    ## Priority 1: replied-to message
    if msg.reply_to_message and msg.reply_to_message.from_user:
        u: User = msg.reply_to_message.from_user
        return u.id, u.first_name

    ## Priority 2: first arg is numeric ID or @username
    if args:
        arg = args[0].lstrip("@")
        if arg.lstrip("-").isdigit():
            uid = int(arg)
            if bot:
                try:
                    chat = await bot.get_chat(uid)
                    return chat.id, chat.first_name or str(uid)
                except Exception:
                    pass
            return uid, f"User {uid}"
        if bot and arg:
            try:
                chat = await bot.get_chat(f"@{arg}")
                return chat.id, chat.first_name or arg
            except Exception as exc:
                log.debug("Username lookup failed for @%s: %s", arg, exc)

    ## Priority 3: text_mention entity
    for ent in msg.entities or []:
        if ent.type == "text_mention" and ent.user:
            return ent.user.id, ent.user.first_name

    ## Priority 4: @mention entity with resolvable username (requires bot)
    if bot:
        text = msg.text or ""
        for ent in msg.entities or []:
            if ent.type == "mention":
                uname = text[ent.offset + 1: ent.offset + ent.length]
                try:
                    chat = await bot.get_chat(f"@{uname}")
                    return chat.id, chat.first_name or uname
                except Exception:
                    pass

    return None, None
