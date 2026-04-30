# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""Resolve a command target from an explicit argument or a reply.

Resolution order is:

1. **Explicit argument** (``@username`` or numeric user id). If the first
   positional argument can be resolved through the Bot API, it wins —
   even when the message is also a reply to someone. Honouring the typed
   argument matches the operator's clearly stated intent and avoids the
   surprising behaviour where replying to an unrelated message silently
   hijacks a moderation command.
2. **Reply-to target.** Used when there are no usable arguments.

The :class:`ResolvedTarget` exposes ``from_args`` so callers can correctly
compute where the optional reason text begins (``args[1:]`` for explicit
arguments, ``args[:]`` for reply targets).
"""
from __future__ import annotations

from telegram import Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes


class ResolvedTarget:
    """A user identified for a moderation command."""

    __slots__ = ("id", "first_name", "username", "raw", "from_args")

    def __init__(
        self,
        user_id: int,
        first_name: str | None,
        username: str | None,
        raw=None,
        from_args: bool = False,
    ):
        self.id = user_id
        self.first_name = first_name or str(user_id)
        self.username = username
        self.raw = raw
        self.from_args = from_args


async def resolve_target(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> ResolvedTarget | None:
    """Return the user the command is operating on, or ``None``.

    Explicit arguments take priority over the reply target. If the first
    argument is provided but cannot be resolved (invalid id, unknown
    username, user has not interacted with the bot), the reply target is
    used instead so the command stays usable.
    """
    msg = update.effective_message
    if msg is None:
        return None

    args = context.args or []

    if args:
        raw = args[0].lstrip("@")
        resolved = None
        try:
            if raw.lstrip("-").isdigit():
                resolved = await context.bot.get_chat(int(raw))
            else:
                resolved = await context.bot.get_chat(raw)
        except TelegramError:
            resolved = None
        if resolved is not None:
            first_name = (
                getattr(resolved, "first_name", None)
                or getattr(resolved, "title", None)
            )
            return ResolvedTarget(
                resolved.id,
                first_name,
                getattr(resolved, "username", None),
                raw=resolved,
                from_args=True,
            )

    if msg.reply_to_message and msg.reply_to_message.from_user:
        u = msg.reply_to_message.from_user
        return ResolvedTarget(
            u.id, u.first_name, u.username, raw=u, from_args=False
        )

    return None


def get_reason(
    context: ContextTypes.DEFAULT_TYPE,
    update: Update,
    target: ResolvedTarget | None = None,
) -> str:
    """Extract the reason text that follows the target token.

    When the target was taken from an explicit argument the first token is
    consumed and the reason is ``args[1:]``. When the target came from a
    reply (or no target was resolved) every argument belongs to the reason.
    """
    args = context.args or []
    if not args:
        return ""
    if target is not None and target.from_args:
        return " ".join(args[1:]).strip()
    msg = update.effective_message
    if msg and msg.reply_to_message and msg.reply_to_message.from_user:
        return " ".join(args).strip()
    return " ".join(args[1:]).strip()
