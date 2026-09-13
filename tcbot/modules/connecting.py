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

# * Connect runtime prose lives in connecting.toml [state].

# ─────────────────────── Rate-limiter constants ──────────────────── #
_RL_PERIOD_S: int = 60
_RL_LIMIT: int = 3


# ────────────────────── Module & Help Message ───────────────────── #

__module_name__ = "Connect"


def get_help(locale: str | None = None) -> replies.HelpEntry:
    """Build this module's help entry in the given locale."""
    overview = t("connecting.help.overview", locale, community=cfg.community_name)
    sections: list[tuple[str, str]] = [
        (
            replies.sec_commands(locale),
            t("connecting.help.commands.body", locale),
        ),
        replies.who_section(t("connecting.help.who.body", locale), locale),
        replies.where_section(
            t("connecting.help.where.body", locale, community=cfg.community_name),
            locale,
        ),
        (
            replies.sec_what(locale),
            t("connecting.help.what.body", locale, community=cfg.community_name),
        ),
        (
            "Required permissions",
            t("connecting.help.permissions.body", locale),
        ),
        (
            "Notes",
            t("connecting.help.notes.body", locale),
        ),
        (
            replies.sec_examples(locale),
            t("connecting.help.examples.body", locale),
        ),
    ]
    return {"name": __module_name__, "overview": overview, "sections": sections}


__help__: replies.HelpEntry = get_help()
__help_text__ = __help__["overview"]
__help_sections__ = __help__["sections"]


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
            t("connecting.state.admin_required", locale, plain=True),
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
            t("connecting.state.primary_group", locale, plain=True),
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
            connection.already_connected_message(locale),
            log_label="cmd_tctc already-connected",
            parse_mode=None,
        )
        return

    if pending:
        await safe_reply(
            msg,
            t("connecting.state.pending_request", locale, plain=True),
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
            connection.perms_required_message(locale),
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
            t("connecting.state.connect_failed", locale, plain=True),
            log_label="connect failure",
            parse_mode=None,
        )
        return
    await safe_reply(
        msg,
        connection.connected_message(locale),
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
