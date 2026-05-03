# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""Resolve a ban target (user_id, first_name) from command context."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from telegram import Bot, Message, Update, User

log = logging.getLogger(__name__)


@dataclass
class ResolvedTarget:
    """A resolved Telegram user target with a guaranteed display name."""

    id: int
    first_name: str | None
    username: str | None = None
    raw: object = field(default=None, compare=False, repr=False)

    def __post_init__(self) -> None:
        if not self.first_name:
            self.first_name = str(self.id)


def get_reason(context: object, update: object) -> str:
    """Extract the ban/action reason from command arguments.

    When the command was used as a reply, *all* args are the reason.
    When the command used an explicit target (@user or user_id as first arg),
    the first arg is skipped and the rest form the reason.
    """
    msg = getattr(update, "effective_message", None)
    reply = getattr(msg, "reply_to_message", None) if msg else None
    is_reply = bool(reply and getattr(reply, "from_user", None))

    args: list[str] = list(getattr(context, "args", None) or [])
    if is_reply:
        return " ".join(args)
    return " ".join(args[1:])


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
