# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""Group disconnect handlers – removes a group from the federation."""

from __future__ import annotations

import asyncio
import logging

from telegram import Update
from telegram.ext import ContextTypes, MessageHandler

from tcbot import cfg
from tcbot import database as db
from tcbot.modules.helper import decorators, parse_logmsg
from tcbot.modules.helper.formatter import code
from tcbot.utils.prefixes import build_prefixed_filters, parse_cmd_args

log = logging.getLogger(__name__)


# ────────────────────── Module & Help Message ───────────────────── #

__module_name__ = "Disconnect"
__help_text__ = (
    "<b>Commands & Aliases</b>\n"
    "<code>/tcdisconnect</code> (alias: <code>/tcdiscon</code>)\n"
    "<code>/rmtc</code>\n\n"
    "<b>Who can use it</b>\n"
    "<code>/tcdisconnect</code>: the group owner or TC Staff (Admin and above).\n"
    "<code>/rmtc</code>: TC Staff only.\n\n"
    "<b>Where to use it</b>\n"
    "<code>/tcdisconnect</code>: inside the group you want to disconnect.\n"
    "<code>/rmtc</code>: exec group or bot PM (works remotely by chat ID).\n\n"
    "<b>What it does</b>\n"
    f"<code>/tcdisconnect</code>: removes the current group from {cfg.community_name}, "
    "posts a disconnection log entry, and causes the bot to leave the group.\n\n"
    "<code>/rmtc</code>: force-removes a group from the federation by chat ID. Use this for "
    "groups the bot has already been kicked from, or to remove a group remotely without being "
    "inside it. A log entry is still posted.\n\n"
    "<b>Examples</b>\n"
    "Run <code>/tcdisconnect</code> inside the group to disconnect it.\n"
    "<code>/rmtc -1001234567890</code> - force-remove a group by chat ID."
)


# ────────── Command to Disconnect a Group </tcdisconnect> ───────── #


@decorators.ratelimiter(limit=3, period=60)
@decorators.log_execution
async def cmd_tcdisconnect(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    user = update.effective_user

    if chat.type == "private":
        await update.effective_message.reply_text("Use this command in a group.")
        return

    if not await db.groups_db.is_connected(chat.id):
        await update.effective_message.reply_text(
            f"This group is not connected to {cfg.community_name}."
        )
        return

    # * staff check and group membership check run in parallel
    is_tc_staff, member = await asyncio.gather(
        db.admins_db.is_staff(user.id),
        ctx.bot.get_chat_member(chat.id, user.id),
    )
    is_group_owner = member.status == "creator"

    if not is_tc_staff and not is_group_owner:
        await update.effective_message.reply_text(
            "Only the group owner or TC admins can disconnect this group."
        )
        return

    lc, lt = cfg.logs
    # * deactivate, log, reply, and leave all run in parallel
    await asyncio.gather(
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


# ───────────── Command to Force-Remove a Group </rmtc> ──────────── #


@decorators.ratelimiter(limit=5, period=60)
@decorators.staff_only
@decorators.log_execution
async def cmd_rmtc(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    args = parse_cmd_args(update.effective_message.text)
    if not args or not args[0].lstrip("-").isdigit():
        await update.effective_message.reply_text("Usage: /rmtc <chat_id>")
        return

    chat_id = int(args[0])
    removed = await db.groups_db.deactivate_group(chat_id)
    if removed:
        lc, lt = cfg.logs
        # * log, leave, and reply all run in parallel
        await asyncio.gather(
            ctx.bot.send_message(
                lc,
                parse_logmsg.group_disconnected_log(
                    chat_id,
                    str(chat_id),
                    update.effective_user.id,
                    update.effective_user.first_name,
                ),
                parse_mode="HTML",
                message_thread_id=lt,
            ),
            ctx.bot.leave_chat(chat_id),
            update.effective_message.reply_text(
                f"Group {code(str(chat_id))} has been disconnected from {cfg.community_name}.",
                parse_mode="HTML",
            ),
            return_exceptions=True,
        )
    else:
        await update.effective_message.reply_text("Group not found or already removed.")


# ──────────────────────────── Handlers ──────────────────────────── #

_DISCONNECT_CMDS = build_prefixed_filters("tcdisconnect") | build_prefixed_filters(
    "tcdiscon"
)
_RMTC_CMDS = build_prefixed_filters("rmtc")


__handlers__ = [
    MessageHandler(_DISCONNECT_CMDS, cmd_tcdisconnect),
    MessageHandler(_RMTC_CMDS, cmd_rmtc),
]
