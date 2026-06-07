# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Studio

"""Group connect command handler: manages federation group onboarding."""

from __future__ import annotations

import asyncio
import logging

from telegram import Update
from telegram.ext import (
    CallbackQueryHandler,
    ChatMemberHandler,
    ContextTypes,
    MessageHandler,
)

from tcbot import cfg
from tcbot import database as db
from tcbot.modules.helper import decorators, replies
from tcbot.modules.helper.workflows.connected_flow import connection
from tcbot.utils.prefixes import build_prefixed_filters

log = logging.getLogger(__name__)

# ──────────────── User-facing reply constants ──────────────────── #

_ERR_ADMIN_REQUIRED = "Only group admins can request to connect."
_ERR_PENDING_REQUEST = "A connect request for this group is already pending."

_TG_TIMEOUT = 3.0

# ─────────────────────── Rate-limiter constants ──────────────────── #
_RL_PERIOD_S: int = 60
_RL_LIMIT: int = 3


# ────────────────────── Module & Help Message ───────────────────── #

__module_name__ = "Connect"
__help_text__ = (
    f"Connects your group to the {cfg.community_name} federation so federation bans, "
    f"mutes, and broadcasts are applied automatically."
)

__help_sections__: list[tuple[str, str]] = [
    (
        replies.SEC_COMMANDS,
        "<code>/tcconnect</code> (alias: <code>/tccon</code>)",
    ),
    (
        replies.SEC_WHO,
        "Group admins and creators only (checked per-group).",
    ),
    (
        replies.SEC_WHERE,
        f"Inside the group you want to connect to {cfg.community_name}.",
    ),
    (
        replies.SEC_WHAT,
        f"Connects your group to the {cfg.community_name} federation. Once connected:\n"
        f"- Federation bans are automatically enforced: currently banned users are removed, "
        f"and newly banned users are kicked on ban.\n"
        f"- Federation mutes are applied when issued.\n"
        f"- Broadcast messages from TC Staff are forwarded to your group.",
    ),
    (
        "Required permissions",
        "Before running the command, make the bot a group admin with these three "
        "permissions: <b>Delete Messages</b>, <b>Ban Users</b>, and <b>Invite Users "
        "via Link</b>.",
    ),
    (
        "Notes",
        "If a connect request is already pending for your group, a second request will be "
        "rejected; wait for TC Staff to process the existing one.\n\n"
        "When the bot is first added to a group, it automatically prompts the group owner "
        "to connect, so you can also just add the bot and follow that prompt.",
    ),
    (
        "Example",
        "Make the bot a group admin, then run <code>/tcconnect</code> inside the group.",
    ),
]


# ───────────── Command to Connect a Group </tcconnect> ──────────── #


@decorators.ratelimiter(limit=_RL_LIMIT, period=_RL_PERIOD_S)
@decorators.log_execution
async def cmd_tcconnect(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Request to connect the current group to the federation.

    Group-only command. Checks admin status, existing connection, and pending
    requests in parallel (Telegram lookup is bounded to avoid stalls). On
    success, creates a pending request and notifies the main group for founder
    approval.
    """
    chat = update.effective_chat
    user = update.effective_user

    if chat.type == "private":
        await update.effective_message.reply_text(replies.ERR_GROUP_ONLY)
        return

    # * Telegram lookup + DB reads run in parallel; member check is bounded so a
    # * stalled Telegram API never blocks the user-facing reply.
    member, is_connected, pending = await asyncio.gather(
        asyncio.wait_for(
            ctx.bot.get_chat_member(chat.id, user.id), timeout=_TG_TIMEOUT
        ),
        db.groups_db.is_connected(chat.id),
        db.groups_db.get_pending(chat.id),
        return_exceptions=True,
    )
    if isinstance(member, BaseException):
        log.debug("get_chat_member failed for %d/%d: %s", chat.id, user.id, member)
        await update.effective_message.reply_text(replies.ERR_ROLE_VERIFY)
        return

    if member.status not in ("administrator", "creator"):
        await update.effective_message.reply_text(_ERR_ADMIN_REQUIRED)
        return

    if isinstance(is_connected, BaseException):
        is_connected = False
    if isinstance(pending, BaseException):
        pending = None

    if is_connected:
        await update.effective_message.reply_text(
            connection.already_connected_message()
        )
        return

    if pending:
        await update.effective_message.reply_text(_ERR_PENDING_REQUEST)
        return

    try:
        bot_member = await asyncio.wait_for(
            ctx.bot.get_chat_member(chat.id, ctx.bot.id), timeout=_TG_TIMEOUT
        )
    except Exception as exc:
        log.debug("Could not verify bot permissions for %d: %s", chat.id, exc)
        await update.effective_message.reply_text(replies.ERR_ROLE_VERIFY)
        return

    if not connection.check_perms(bot_member):
        await update.effective_message.reply_text(connection.perms_required_message())
        return

    # * complete_join returns None - reply can be sent in parallel
    await asyncio.gather(
        connection.complete_join(
            chat.id, chat.title or "", user.id, user.first_name, ctx.bot
        ),
        update.effective_message.reply_text(connection.connected_message()),
        return_exceptions=True,
    )


# ──────────────────────────── Handlers ──────────────────────────── #

_CONNECT_CMDS = build_prefixed_filters("tcconnect") | build_prefixed_filters("tccon")

__handlers__ = [
    ChatMemberHandler(connection.on_bot_added, ChatMemberHandler.MY_CHAT_MEMBER),
    MessageHandler(_CONNECT_CMDS, cmd_tcconnect),
    CallbackQueryHandler(
        connection.on_join_decision,
        pattern=rf"^({connection.join_callback}|{connection.cancel_callback})$",
    ),
]
