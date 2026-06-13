# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Studio

"""Group disconnect handlers: removes a group from the federation."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from telegram.ext import ContextTypes, MessageHandler

from tcbot import cfg
from tcbot import database as db
from tcbot.modules.helper import decorators, parse_logmsg, replies
from tcbot.modules.helper.formatter import code, esc
from tcbot.utils.prefixes import build_prefixed_filters, parse_cmd_args

if TYPE_CHECKING:
    from telegram import Update

log = logging.getLogger(__name__)

# ──────────────── User-facing reply constants ──────────────────── #

_MSG_RMTC_USAGE = "Usage: /rmtc <chat_id>"

_TG_TIMEOUT = 3.0

# ─────────────────────── Rate-limiter constants ──────────────────── #
_RL_PERIOD_S: int = 60
_RL_DISCONNECT_LIMIT: int = 3
_RL_RMTC_LIMIT: int = 5


# ────────────────────── Module & Help Message ───────────────────── #

_CNAME = esc(cfg.community_name)

__module_name__ = "Disconnect"
__help_text__ = (
    f"Removes a group from {_CNAME}. Use <code>/tcdisconnect</code> from "
    f"inside the group, or <code>/rmtc</code> remotely with a chat ID."
)

__help_sections__: list[tuple[str, str]] = [
    (
        replies.SEC_COMMANDS,
        "<code>/tcdisconnect</code> (alias: <code>/tcdiscon</code>)\n"
        "<code>/rmtc</code>",
    ),
    (
        replies.SEC_WHO,
        "<b>/tcdisconnect</b>: the group owner or TC Staff (Admin and above).\n"
        "<b>/rmtc</b>: TC Staff only.",
    ),
    (
        replies.SEC_WHERE,
        "<b>/tcdisconnect</b>: inside the group you want to disconnect.\n"
        "<b>/rmtc</b>: exec group or bot PM (works remotely by chat ID).",
    ),
    (
        replies.SEC_WHAT,
        f"<b>/tcdisconnect</b>: removes the current group from {_CNAME}, posts a "
        f"disconnection log entry, and causes the bot to leave the group.\n\n"
        f"<b>/rmtc</b>: force-removes a group from the federation by chat ID. Use this for "
        f"groups the bot has already been kicked from, or to remove a group remotely without "
        f"being inside it. A log entry is still posted.",
    ),
    (
        replies.SEC_EXAMPLES,
        "Run <code>/tcdisconnect</code> inside the group to disconnect it.\n"
        "<code>/rmtc -1001234567890</code>: force-remove a group by chat ID.",
    ),
]


# ────────── Command to Disconnect a Group </tcdisconnect> ───────── #


@decorators.ratelimiter(limit=_RL_DISCONNECT_LIMIT, period=_RL_PERIOD_S)
@decorators.log_execution
async def cmd_tcdisconnect(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Request to disconnect the current group from the federation.

    Group-only command. Confirms the group is connected, checks staff status
    and group admin membership in parallel (bounded Telegram call), then posts
    a confirmation card to the main group for founder approval.
    """
    chat = update.effective_chat
    user = update.effective_user

    if chat.type == "private":
        try:
            await update.effective_message.reply_text(replies.ERR_GROUP_ONLY)
        except Exception as exc:
            log.debug("cmd_tcleave group-only reply failed: %s", exc)
        return

    if not await db.groups_db.is_connected(chat.id):
        try:
            await update.effective_message.reply_text(
                f"This group is not connected to {cfg.community_name}."
            )
        except Exception as exc:
            log.debug("cmd_tcleave not-connected reply failed: %s", exc)
        return

    # * Staff check + group membership check + Telegram lookup run in parallel.
    # * The Telegram call is bounded so a stalled API never blocks the reply.
    is_tc_staff, member = await asyncio.gather(
        db.users_roles.is_staff(user.id),
        asyncio.wait_for(
            ctx.bot.get_chat_member(chat.id, user.id), timeout=_TG_TIMEOUT
        ),
        return_exceptions=True,
    )
    if isinstance(member, BaseException):
        log.debug("Disconnect: get_chat_member failed for %d: %s", chat.id, member)
        try:
            await update.effective_message.reply_text(replies.ERR_ROLE_VERIFY)
        except Exception as exc:
            log.debug("cmd_tcleave role-verify reply failed: %s", exc)
        return
    if isinstance(is_tc_staff, BaseException):
        is_tc_staff = False
    is_group_owner = member.status == "creator"

    if not is_tc_staff and not is_group_owner:
        try:
            await update.effective_message.reply_text(
                "Only the group owner or TC admins can disconnect this group."
            )
        except Exception as exc:
            log.debug("cmd_tcleave not-authorized reply failed: %s", exc)
        return

    lc, lt = cfg.logs
    # * deactivate, log, reply, and leave all run in parallel
    deact_r, log_r, reply_r, leave_r = await asyncio.gather(
        db.groups_db.deactivate_group(chat.id),
        ctx.bot.send_message(
            lc,
            parse_logmsg.group_disconnected_log(
                chat.id, chat.title or "Unknown", user.id, user.first_name
            ),
            parse_mode="HTML",
            message_thread_id=lt,
        ),
        update.effective_message.reply_text(
            f"This group has been disconnected from {cfg.community_name}."
        ),
        ctx.bot.leave_chat(chat.id),
        return_exceptions=True,
    )
    if isinstance(deact_r, BaseException):
        log.error(
            "deactivate_group failed for chat %d during tcleave: %s", chat.id, deact_r
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
    msg = update.effective_message
    admin = update.effective_user
    args = parse_cmd_args(msg.text)
    if not args or not args[0].lstrip("-").isdigit():
        try:
            await msg.reply_text(_MSG_RMTC_USAGE)
        except Exception as exc:
            log.debug("cmd_rmtc usage reply failed: %s", exc)
        return

    chat_id = int(args[0])
    removed = await db.groups_db.deactivate_group(chat_id)
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
                parse_mode="HTML",
                message_thread_id=lt,
            ),
            ctx.bot.leave_chat(chat_id),
            msg.reply_text(
                f"Group {code(str(chat_id))} has been disconnected from {esc(cfg.community_name)}.",
                parse_mode="HTML",
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
        try:
            await msg.reply_text(replies.ERR_GROUP_NOT_FOUND)
        except Exception as exc:
            log.debug("cmd_rmtc not-found reply failed: %s", exc)


# ──────────────────────────── Handlers ──────────────────────────── #

_DISCONNECT_CMDS = build_prefixed_filters("tcdisconnect") | build_prefixed_filters(
    "tcdiscon"
)
_RMTC_CMDS = build_prefixed_filters("rmtc")


__handlers__ = [
    MessageHandler(_DISCONNECT_CMDS, cmd_tcdisconnect),
    MessageHandler(_RMTC_CMDS, cmd_rmtc),
]
