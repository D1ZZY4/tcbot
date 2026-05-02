# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""Group de-affiliation commands."""
from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes, MessageHandler

from tcbot import database as db
from tcbot.config import cfg
from tcbot.modules.helper import decorators, parse_logmsg
from tcbot.modules.helper.formatter import code
from tcbot.utils.prefixes import build_prefixed_filters, parse_cmd_args

log = logging.getLogger(__name__)

__module_name__ = "Disaffiliate"
__help_text__ = (
    "<code>/detc</code> – remove the current group from TCF (group owner or TC admin).\n"
    "Aliases: <code>/leavetc</code>, <code>/untc</code>\n\n"
    "<code>/rmtc</code> <i>&lt;chat_id&gt;</i> – force-remove a group by ID (TC staff only).\n"
    "Aliases: <code>/removetc</code>, <code>/deletetc</code>"
)


async def cmd_detc(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    user = update.effective_user

    if chat.type == "private":
        await update.effective_message.reply_text("Use this command in a group.")
        return

    if not await db.groups_db.is_affiliated(chat.id):
        await update.effective_message.reply_text("This group is not affiliated with TCF.")
        return

    is_tc_staff = await db.admins_db.is_staff(user.id)
    member = await ctx.bot.get_chat_member(chat.id, user.id)
    is_group_owner = member.status == "creator"

    if not is_tc_staff and not is_group_owner:
        await update.effective_message.reply_text(
            "Only the group owner or Transsion Core admins can disaffiliate this group."
        )
        return

    await db.groups_db.deactivate_group(chat.id)

    lc, lt = cfg.logs
    try:
        await ctx.bot.send_message(
            lc,
            parse_logmsg.group_disconnected_log(chat.id, chat.title or "Unknown", user.id, user.first_name),
            parse_mode="HTML",
            message_thread_id=lt,
        )
    except Exception:
        pass

    await update.effective_message.reply_text(
        "This group has been removed from the Transsion Core Federation."
    )
    try:
        await ctx.bot.leave_chat(chat.id)
    except Exception:
        pass


@decorators.staff_only
async def cmd_rmtc(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    args = parse_cmd_args(update.effective_message.text)
    if not args or not args[0].lstrip("-").isdigit():
        await update.effective_message.reply_text("Usage: /rmtc <chat_id>")
        return

    chat_id = int(args[0])
    removed = await db.groups_db.deactivate_group(chat_id)
    if removed:
        lc, lt = cfg.logs
        try:
            await ctx.bot.send_message(
                lc,
                parse_logmsg.group_disconnected_log(
                    chat_id, str(chat_id), update.effective_user.id, update.effective_user.first_name,
                ),
                parse_mode="HTML",
                message_thread_id=lt,
            )
        except Exception:
            pass
        try:
            await ctx.bot.leave_chat(chat_id)
        except Exception:
            pass
        await update.effective_message.reply_text(
            f"Group {code(str(chat_id))} has been removed from the federation.", parse_mode="HTML",
        )
    else:
        await update.effective_message.reply_text("Group not found or already removed.")


## Spec aliases: /detc, /leavetc, /untc
_DETC_FILTER = (
    build_prefixed_filters("detc")
    | build_prefixed_filters("leavetc")
    | build_prefixed_filters("untc")
)
## Spec aliases: /rmtc, /removetc, /deletetc
_RMTC_FILTER = (
    build_prefixed_filters("rmtc")
    | build_prefixed_filters("removetc")
    | build_prefixed_filters("deletetc")
)

__handlers__ = [
    MessageHandler(_DETC_FILTER, cmd_detc),
    MessageHandler(_RMTC_FILTER, cmd_rmtc),
]
