# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""Target extraction helpers – ``extract_target()``, ``ResolvedTarget``, and ``resolve_identity()``."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Protocol

from telegram import Bot, Message, Update, User
from telegram.error import TelegramError

from tcbot.database import users_db
from tcbot.database.documents import UserDoc

log = logging.getLogger(__name__)


class _ArgsContext(Protocol):
    args: list[str]


class _ReplyMessage(Protocol):
    from_user: User | None


class _ReasonMessage(Protocol):
    reply_to_message: _ReplyMessage | None


class _ReasonUpdate(Protocol):
    effective_message: _ReasonMessage | None


class _BotContext(Protocol):
    bot: Bot


# ── Target resolution ──────────────────────────────────────────────────────


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


def get_reason(context: _ArgsContext, update: _ReasonUpdate) -> str:
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
    """Return (user_id, first_name) resolved from args, reply, entity, or mention.

    Resolution order (explicit args always win over reply):
    1. Numeric ID or @username in args[0] - highest priority.
    2. Reply-to-message sender - only when no explicit arg was given.
    3. text_mention entity in the message.
    4. @mention entity resolved via bot.get_chat().
    Returns (None, None) if no valid target can be resolved.
    """
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


# ── Identity resolution ────────────────────────────────────────────────────


@dataclass(frozen=True)
class UserIdentity:
    """Resolved identity for a Telegram user."""

    user_id: int
    display_name: str
    username: str | None

    @property
    def name_with_username(self) -> str:
        if self.username:
            return f"{self.display_name} (@{self.username})"
        return self.display_name


class _MembersRepo:
    """Thin adapter over the member-cache collection."""

    async def find_latest_for_user(self, user_id: int) -> UserDoc | None:
        return await users_db.get_user(user_id)


members_repo = _MembersRepo()


async def resolve_identity(ctx: _BotContext, user_id: int) -> UserIdentity:
    """Resolve a user's display identity.

    Resolution order:
    1. ``ctx.bot.get_chat`` – live data from Telegram.
    2. ``members_repo.find_latest_for_user`` – member-cache fallback.
    3. Bare user_id string – ultimate fallback.
    """
    try:
        chat = await ctx.bot.get_chat(user_id)
        first = getattr(chat, "first_name", None)
        title = getattr(chat, "title", None)
        uname = getattr(chat, "username", None)
        if first or title:
            return UserIdentity(
                user_id=user_id,
                display_name=str(first or title),
                username=uname,
            )
    except TelegramError:
        pass

    cached = await members_repo.find_latest_for_user(user_id)
    if cached:
        first = cached.get("first_name")
        uname = cached.get("username")
        if first:
            display = first
        elif uname:
            display = f"@{uname}"
        else:
            display = str(user_id)
        return UserIdentity(user_id=user_id, display_name=display, username=uname)

    return UserIdentity(user_id=user_id, display_name=str(user_id), username=None)
