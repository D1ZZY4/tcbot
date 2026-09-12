# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Group disconnect handlers: removes a group from the federation."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from telegram.ext import ContextTypes, MessageHandler

from tcbot import cfg
from tcbot import database as db
from tcbot.modules.helper import decorators, parse_logmsg, replies
from tcbot.modules.helper.identity import ANONYMOUS_BOT_ID
from tcbot.modules.helper.locale import locale_for_update
from tcbot.modules.helper.parse_editmsg import safe_reply
from tcbot.utils.formatter import code
from tcbot.utils.i18n import Safe, t
from tcbot.utils.prefixes import build_prefixed_filters, parse_cmd_args
from tcbot.utils.time_and_date import TELEGRAM_LOOKUP_TIMEOUT

if TYPE_CHECKING:
    from telegram import Update

log = logging.getLogger(__name__)

# * Disconnect runtime prose lives in disconnecting.toml [state]/[removed].

# ─────────────────────── Rate-limiter constants ──────────────────── #
_RL_PERIOD_S: int = 60
_RL_DISCONNECT_LIMIT: int = 3
_RL_RMTC_LIMIT: int = 5


# ────────────────────── Module & Help Message ───────────────────── #

__module_name__ = "Disconnect"


def get_help(locale: str | None = None) -> replies.HelpEntry:
    """Build this module's help entry in the given locale."""
    overview = t("disconnecting.help.overview", locale, community=cfg.community_name)
    sections: list[tuple[str, str]] = [
        (
            replies.sec_commands(locale),
            t("disconnecting.help.commands.body", locale),
        ),
        replies.who_section(t("disconnecting.help.who.body", locale), locale),
        replies.where_section(t("disconnecting.help.where.body", locale), locale),
        (
            replies.sec_what(locale),
            t("disconnecting.help.what.body", locale, community=cfg.community_name),
        ),
        (
            replies.sec_examples(locale),
            t("disconnecting.help.examples.body", locale),
        ),
    ]
    return {"name": __module_name__, "overview": overview, "sections": sections}


__help__: replies.HelpEntry = get_help()
__help_text__ = __help__["overview"]
__help_sections__ = __help__["sections"]


# ────────── Command to Disconnect a Group </tcdisconnect> ───────── #


@decorators.ratelimiter(limit=_RL_DISCONNECT_LIMIT, period=_RL_PERIOD_S)
@decorators.log_execution
async def cmd_tcdisconnect(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Request to disconnect the current group from the federation.

    Group-only command. Confirms the group is connected, checks staff status
    and group admin membership in parallel (bounded Telegram call), then
    deactivates the group record first and leaves the chat.
    """
    chat = update.effective_chat
    user = update.effective_user
    msg = update.effective_message
    if chat is None or user is None or msg is None:
        return
    locale = await locale_for_update(update)

    if chat.type == "private":
        await safe_reply(
            msg,
            replies.err_group_only(locale, plain=True),
            log_label="cmd_tcleave group-only",
            parse_mode=None,
        )
        return

    # * Primary groups (main, exec) are required destinations for ban /
    # * unban / mute / warn fan-out and the federation log channel. They
    # * must never be disconnected by the group owner; the bot would
    # * lose primary-group enforcement and log delivery.
    if cfg.is_primary_group(chat.id):
        await safe_reply(
            msg,
            t("disconnecting.state.primary_refused", locale, plain=True),
            log_label="cmd_tcleave primary-group",
            parse_mode=None,
        )
        return

    # * Pre-fetch all three in parallel: is_connected (cache-backed), staff check,
    # * and the Telegram member lookup (dominates latency at 50-200 ms).
    # * Front-loading the Telegram call eliminates it from the sequential path.
    is_connected, is_tc_staff, member = await asyncio.gather(
        db.groups_db.is_connected(chat.id),
        db.users_roles.is_staff(user.id),
        asyncio.wait_for(
            ctx.bot.get_chat_member(chat.id, user.id), timeout=TELEGRAM_LOOKUP_TIMEOUT
        ),
        return_exceptions=True,
    )
    if isinstance(is_connected, BaseException):
        log.warning("is_connected check failed for chat=%d: %s", chat.id, is_connected)
        await safe_reply(
            msg,
            t("disconnecting.state.status_failed", locale, plain=True),
            log_label="cmd_tcleave status-check-failed",
            parse_mode=None,
        )
        return
    if not is_connected:
        await safe_reply(
            msg,
            t(
                "disconnecting.state.not_connected",
                locale,
                community=cfg.community_name,
                plain=True,
            ),
            log_label="cmd_tcleave not-connected",
            parse_mode=None,
        )
        return
    if isinstance(member, BaseException):
        log.debug("Disconnect: get_chat_member failed for %d: %s", chat.id, member)
        await safe_reply(
            msg,
            replies.err_role_verify(locale, plain=True),
            log_label="cmd_tcleave role-verify",
            parse_mode=None,
        )
        return
    if isinstance(is_tc_staff, BaseException):
        is_tc_staff = False
    is_group_owner = member.status == "creator"

    if not is_tc_staff and not is_group_owner:
        if user.id == ANONYMOUS_BOT_ID:
            msg_text = t("disconnecting.state.anon_admin", locale, plain=True)
        else:
            msg_text = t("disconnecting.state.not_authorized", locale, plain=True)
        await safe_reply(
            msg, msg_text, log_label="cmd_tcleave not-authorized", parse_mode=None
        )
        return

    lc, lt = cfg.logs
    # * Deactivate first: only leave after the DB confirms, otherwise a
    # * deactivate failure leaves a ghost (bot gone, DB still active).
    try:
        deactivated = await db.groups_db.deactivate_group(chat.id)
    except Exception:
        log.exception("deactivate_group failed for chat %d during tcleave", chat.id)
        deactivated = False
    if not deactivated:
        await safe_reply(
            msg,
            t("disconnecting.state.deactivate_failed", locale, plain=True),
            log_label="cmd_tcleave deactivate-failed",
            parse_mode=None,
        )
        return
    log_r, reply_r, leave_r = await asyncio.gather(
        ctx.bot.send_message(
            lc,
            parse_logmsg.group_disconnected_log(
                chat.id, chat.title or "Unknown", user.id, user.first_name
            ),
            parse_mode="MarkdownV2",
            message_thread_id=lt,
        ),
        msg.reply_text(
            t(
                "disconnecting.state.disconnected",
                locale,
                community=cfg.community_name,
                plain=True,
            )
        ),
        ctx.bot.leave_chat(chat.id),
        return_exceptions=True,
    )
    if isinstance(log_r, BaseException):
        log.debug("tcleave log send failed for chat %d: %s", chat.id, log_r)
    if isinstance(reply_r, BaseException):
        log.debug("tcleave reply failed for chat %d: %s", chat.id, reply_r)
    if isinstance(leave_r, BaseException):
        log.debug("tcleave leave_chat failed for chat %d: %s", chat.id, leave_r)


# ───────────── Command to Force-Remove a Group </rmtc> ──────────── #


@decorators.ratelimiter(limit=_RL_RMTC_LIMIT, period=_RL_PERIOD_S)
@decorators.staff_only
@decorators.log_execution
async def cmd_rmtc(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Force-remove a group from the federation by chat ID (staff command).

    Parses the numeric chat ID from the command argument, deactivates the group
    record, then fans out a log message, a bot leave, and a confirmation reply
    in parallel.
    """
    locale = await locale_for_update(update)
    msg = update.effective_message
    admin = update.effective_user
    if msg is None or admin is None:
        return
    args = parse_cmd_args(msg.text)
    if not args or not args[0].lstrip("-").isdigit():
        await safe_reply(
            msg,
            t("disconnecting.state.usage", locale, plain=True),
            log_label="cmd_rmtc usage",
            parse_mode=None,
        )
        return

    chat_id = int(args[0])

    # * Primary groups (main, exec) are required destinations for ban /
    # * unban / mute / warn fan-out and the federation log channel. They
    # * must never be force-disconnected by /rmtc; the bot would lose
    # * primary-group enforcement and log delivery.
    if cfg.is_primary_group(chat_id):
        await safe_reply(
            msg,
            t("disconnecting.state.primary_refused", locale, plain=True),
            log_label="cmd_rmtc primary-group",
            parse_mode=None,
        )
        return

    # * Mirror cmd_tcdisconnect: never leave on an unconfirmed DB write,
    # * and never crash out without a reply on a DB outage.
    try:
        removed = await db.groups_db.deactivate_group(chat_id)
    except Exception:
        log.exception("deactivate_group failed for chat %d during rmtc", chat_id)
        await safe_reply(
            msg,
            t("disconnecting.state.rmtc_failed", locale, plain=True),
            log_label="cmd_rmtc deactivate-failed",
            parse_mode=None,
        )
        return
    if removed:
        lc, lt = cfg.logs
        # * log, leave, and reply all run in parallel
        log_r, leave_r, reply_r = await asyncio.gather(
            ctx.bot.send_message(
                lc,
                parse_logmsg.group_disconnected_log(
                    chat_id,
                    str(chat_id),
                    admin.id,
                    admin.first_name,
                ),
                parse_mode="MarkdownV2",
                message_thread_id=lt,
            ),
            ctx.bot.leave_chat(chat_id),
            msg.reply_text(
                t(
                    "disconnecting.removed.body",
                    locale,
                    id=Safe(code(str(chat_id))),
                    community=cfg.community_name,
                ),
                parse_mode="MarkdownV2",
            ),
            return_exceptions=True,
        )
        if isinstance(log_r, BaseException):
            log.debug("rmtc log send failed for chat %d: %s", chat_id, log_r)
        if isinstance(leave_r, BaseException):
            log.debug("rmtc leave_chat failed for chat %d: %s", chat_id, leave_r)
        if isinstance(reply_r, BaseException):
            log.debug("rmtc reply failed for chat %d: %s", chat_id, reply_r)
    else:
        await safe_reply(
            msg,
            replies.err_group_not_found(locale, plain=True),
            log_label="cmd_rmtc not-found",
            parse_mode=None,
        )


# ──────────────────────────── Handlers ──────────────────────────── #

_DISCONNECT_CMDS = build_prefixed_filters("tcdisconnect") | build_prefixed_filters(
    "tcdiscon"
)
_RMTC_CMDS = build_prefixed_filters("rmtc")


__handlers__ = [
    MessageHandler(_DISCONNECT_CMDS, cmd_tcdisconnect),
    MessageHandler(_RMTC_CMDS, cmd_rmtc),
]
