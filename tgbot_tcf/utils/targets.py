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

Whenever the explicit-argument path resolves through ``bot.get_chat`` the
identity is also cached via :func:`tgbot_tcf.utils.users.cache_identity` so
subsequent log composition (``resolve_identity``) can avoid a second API
round-trip and so the user's last-known display name stays fresh in the
member cache even when they are not present in the operator's group.
"""
from __future__ import annotations

from telegram import Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from .users import schedule_cache_identity


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
        self.first_name = first_name or (
            f"@{username}" if username else str(user_id)
        )
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
    chat_id = msg.chat.id if msg.chat else None

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
            username = getattr(resolved, "username", None)
            schedule_cache_identity(
                resolved.id,
                first_name=first_name,
                username=username,
                chat_id=chat_id,
            )
            return ResolvedTarget(
                resolved.id,
                first_name,
                username,
                raw=resolved,
                from_args=True,
            )

    if msg.reply_to_message and msg.reply_to_message.from_user:
        u = msg.reply_to_message.from_user
        schedule_cache_identity(
            u.id,
            first_name=u.first_name,
            username=u.username,
            chat_id=chat_id,
        )
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
