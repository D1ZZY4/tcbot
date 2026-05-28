# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""Target extraction helpers – ResolvedTarget and extract_target()."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from telegram import Bot, Message, Update, User

log = logging.getLogger(__name__)


# ──────────────────────── Target resolution ─────────────────────── #


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


async def extract_target(
    update: Update,
    args: list[str],
    bot: Bot | None = None,
) -> tuple[int, str] | tuple[None, None]:
    """Return (user_id, first_name) resolved from args, reply, entity, or mention."""
    msg: Message = update.effective_message

    # * Explicit numeric ID or @username always takes priority over reply
    if args:
        arg = args[0].lstrip("@")
        if arg.lstrip("-").isdigit():
            uid = int(arg)
            if bot:
                try:
                    chat = await bot.get_chat(uid)
                    return chat.id, chat.first_name or str(uid)
                except Exception as exc:
                    log.debug("Target lookup failed for %s: %s", arg, exc)
            return uid, f"User {uid}"
        if bot and arg:
            try:
                chat = await bot.get_chat(f"@{arg}")
                return chat.id, chat.first_name or arg
            except Exception as exc:
                log.debug("Username lookup failed for @%s: %s", arg, exc)

    # * Fall back to reply target only when no explicit arg resolved above
    if msg.reply_to_message and msg.reply_to_message.from_user:
        u: User = msg.reply_to_message.from_user
        return u.id, u.first_name

    for ent in msg.entities or []:
        if ent.type == "text_mention" and ent.user:
            return ent.user.id, ent.user.first_name

    if bot:
        text = msg.text or ""
        for ent in msg.entities or []:
            if ent.type == "mention":
                uname = text[ent.offset + 1 : ent.offset + ent.length]
                try:
                    chat = await bot.get_chat(f"@{uname}")
                    return chat.id, chat.first_name or uname
                except Exception as exc:
                    log.debug("Mention lookup failed for @%s: %s", uname, exc)

    return None, None
