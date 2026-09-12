# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Group connect command handler: manages federation group onboarding."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from telegram.ext import (
    CallbackQueryHandler,
    ChatMemberHandler,
    ContextTypes,
    MessageHandler,
)

from tcbot import cfg
from tcbot import database as db
from tcbot.modules.helper import decorators, replies
from tcbot.modules.helper.locale import locale_for_update
from tcbot.modules.helper.parse_editmsg import safe_reply
from tcbot.modules.helper.workflows.connected_flow import connection
from tcbot.utils.i18n import t
from tcbot.utils.prefixes import build_prefixed_filters
from tcbot.utils.time_and_date import TELEGRAM_LOOKUP_TIMEOUT

if TYPE_CHECKING:
    from telegram import Update

log = logging.getLogger(__name__)

# ──────────────── User-facing reply constants ──────────────────── #

_ERR_ADMIN_REQUIRED = "Only group admins can request to connect."
_ERR_PENDING_REQUEST = "A connect request for this group is already pending."

# ─────────────────────── Rate-limiter constants ──────────────────── #
_RL_PERIOD_S: int = 60
_RL_LIMIT: int = 3


# ────────────────────── Module & Help Message ───────────────────── #

__module_name__ = "Connect"
__help_text__ = t("connecting.help.overview", community=cfg.community_name)

__help_sections__: list[tuple[str, str]] = [
    (
        replies.SEC_COMMANDS,
        t("connecting.help.commands.body"),
    ),
    replies.who_section(t("connecting.help.who.body")),
    replies.where_section(
        t("connecting.help.where.body", community=cfg.community_name)
    ),
    (
        replies.SEC_WHAT,
        t("connecting.help.what.body", community=cfg.community_name),
    ),
    (
        "Required permissions",
        t("connecting.help.permissions.body"),
    ),
    (
        "Notes",
        t("connecting.help.notes.body"),
    ),
    (
        replies.SEC_EXAMPLES,
        t("connecting.help.examples.body"),
    ),
]

__help__: replies.HelpEntry = {
    "name": __module_name__,
    "overview": __help_text__,
    "sections": __help_sections__,
}


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
    locale = await locale_for_update(update)
    msg = update.effective_message
    if chat is None or user is None or msg is None:
        return

    if chat.type == "private":
        await safe_reply(
            msg,
            replies.err_group_only(locale, plain=True),
            log_label="cmd_tctc group-only",
            parse_mode=None,
        )
        return

    # * All four calls are independent; fire them in one round-trip.
    # * bot_member is fetched speculatively alongside the user/DB reads so no
    # * extra Telegram round-trip is needed after the early-exit checks.
    member, is_connected, pending, bot_member = await asyncio.gather(
        asyncio.wait_for(
            ctx.bot.get_chat_member(chat.id, user.id), timeout=TELEGRAM_LOOKUP_TIMEOUT
        ),
        db.groups_db.is_connected(chat.id),
        db.groups_db.get_pending(chat.id),
        asyncio.wait_for(
            ctx.bot.get_chat_member(chat.id, ctx.bot.id),
            timeout=TELEGRAM_LOOKUP_TIMEOUT,
        ),
        return_exceptions=True,
    )
    if isinstance(member, BaseException):
        log.debug("get_chat_member failed for %d/%d: %s", chat.id, user.id, member)
        await safe_reply(
            msg,
            replies.err_role_verify(locale, plain=True),
            log_label="cmd_tctc role-verify",
            parse_mode=None,
        )
        return

    if member.status not in ("administrator", "creator"):
        await safe_reply(
            msg,
            _ERR_ADMIN_REQUIRED,
            log_label="cmd_tctc admin-required",
            parse_mode=None,
        )
        return

    # * Primary groups are required enforcement destinations, not federation
    # * members; connecting them would pollute federated_groups with an ID
    # * that fan-out paths unconditionally include.
    if cfg.is_primary_group(chat.id):
        await safe_reply(
            msg,
            "This is a primary group of the federation (main or exec). "
            "Primary groups are not connected via /tcconnect.",
            log_label="cmd_tctc primary-group",
            parse_mode=None,
        )
        return

    if isinstance(is_connected, BaseException):
        is_connected = False
    if isinstance(pending, BaseException):
        pending = None

    if is_connected:
        await safe_reply(
            msg,
            connection.already_connected_message(),
            log_label="cmd_tctc already-connected",
            parse_mode=None,
        )
        return

    if pending:
        await safe_reply(
            msg,
            _ERR_PENDING_REQUEST,
            log_label="cmd_tctc pending-request",
            parse_mode=None,
        )
        return

    if isinstance(bot_member, BaseException):
        log.debug("Could not verify bot permissions for %d: %s", chat.id, bot_member)
        await safe_reply(
            msg,
            replies.err_role_verify(locale, plain=True),
            log_label="cmd_tctc perms-verify",
            parse_mode=None,
        )
        return

    if not connection.check_perms(bot_member):
        await safe_reply(
            msg,
            connection.perms_required_message(),
            log_label="cmd_tctc perms-required",
            parse_mode=None,
        )
        return

    # * Run complete_join first so that we only send a "connected" confirmation
    # * when the DB write (add_group) actually succeeded.  Sending the reply in
    # * parallel was an optimistic pattern that silently swallowed add_group
    # * failures and left the user with a false confirmation.
    try:
        await connection.complete_join(
            chat.id, chat.title or "", user.id, user.first_name, ctx.bot
        )
    except Exception:
        log.exception("complete_join failed for chat %d", chat.id)
        await safe_reply(
            msg,
            "Failed to connect the group due to a server error. Please try again.",
            log_label="connect failure",
            parse_mode=None,
        )
        return
    await safe_reply(
        msg,
        connection.connected_message(),
        log_label=f"connected for chat {chat.id}",
        parse_mode=None,
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
