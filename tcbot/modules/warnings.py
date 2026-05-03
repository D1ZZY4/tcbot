# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""Per-group warning commands."""
from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes, MessageHandler

from tcbot import database as db
from tcbot.modules.helper import decorators, extraction
from tcbot.modules.helper.workflows.warning_conv import warn_conversation
from tcbot.modules.helper.workflows.warning_flow import (
    WARN_LIMIT,
    execute_resetwarns,
    execute_unwarn,
    execute_warnlist,
)
from tcbot.utils.prefixes import build_prefixed_filters, parse_cmd_args

__module_name__ = "Warnings"
__help_text__ = (
    "<b>Commands & Aliases</b>\n"
    f"<code>/tcwarn</code> (alias: <code>/tcw</code>)\n"
    f"<code>/tcunwarn</code> (alias: <code>/tcunw</code>)\n"
    "<code>/warns</code> (alias: <code>/warnlist</code>)\n"
    "<code>/resetwarns</code> (alias: <code>/clearwarns</code>)\n\n"

    "<b>Who can use it</b>\n"
    f"<code>/tcwarn</code>, <code>/tcunwarn</code>, <code>/resetwarns</code>: TC Staff only.\n"
    "<code>/warns</code>: anyone.\n\n"

    "<b>Where to use it</b>\n"
    "Inside any connected group.\n\n"

    "<b>What it does</b>\n"
    f"<code>/tcwarn</code>: warns a user with a reason. Warnings are tracked per-group. "
    f"At <b>{WARN_LIMIT} warnings</b>, the user is automatically banned from the group and their "
    f"warnings are cleared.\n\n"
    "<code>/tcunwarn</code>: removes the user's most recent warning.\n\n"
    "<code>/warns</code>: shows the current warning count and list of reasons for a user.\n\n"
    "<code>/resetwarns</code>: clears all warnings for a user at once.\n\n"

    "<b>How to specify the target</b>\n"
    "Reply to a message, or provide a user ID / @username.\n\n"

    "<b>Flow (/tcwarn)</b>\n"
    "The bot will ask for a reason (required) and proof (optional) before issuing the warning.\n\n"

    "<b>Examples</b>\n"
    "<code>/tcwarn @username spamming</code>\n"
    "<code>/tcw 123456789</code>\n"
    "<code>/tcunwarn @username</code>\n"
    "<code>/warns @username</code>\n"
    "<code>/resetwarns @username</code>"
)


@decorators.staff_only
async def cmd_unwarn(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    args = parse_cmd_args(update.effective_message.text)
    target_id, target_name = await extraction.extract_target(update, args, ctx.bot)
    if not target_id:
        await update.effective_message.reply_text(
            "Specify a target — reply to a message or provide a user ID."
        )
        return
    if target_id == ctx.bot.id:
        await update.effective_message.reply_text("That's me — zero warnings. Nothing to remove.")
        return
    if await db.admins_db.is_owner(target_id):
        await update.effective_message.reply_text("That's the owner — no warnings on record.")
        return
    await execute_unwarn(update, ctx, target_id, target_name or str(target_id))


async def cmd_warnlist(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    args = parse_cmd_args(update.effective_message.text)
    target_id, target_name = await extraction.extract_target(update, args, ctx.bot)
    if not target_id:
        await update.effective_message.reply_text(
            "Specify a target — reply to a message or provide a user ID."
        )
        return
    await execute_warnlist(update, ctx, target_id, target_name or str(target_id))


@decorators.staff_only
async def cmd_resetwarns(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    args = parse_cmd_args(update.effective_message.text)
    target_id, target_name = await extraction.extract_target(update, args, ctx.bot)
    if not target_id:
        await update.effective_message.reply_text(
            "Specify a target — reply to a message or provide a user ID."
        )
        return
    if target_id == ctx.bot.id:
        await update.effective_message.reply_text("That's me — already at zero. Nothing to clear.")
        return
    if await db.admins_db.is_owner(target_id):
        await update.effective_message.reply_text("That's the owner — no warnings to clear.")
        return
    await execute_resetwarns(update, ctx, target_id, target_name or str(target_id))


_UNWARN_FILTER   = build_prefixed_filters("tcunwarn") | build_prefixed_filters("tcunw")
_WARNLIST_FILTER = build_prefixed_filters("warns")    | build_prefixed_filters("warnlist")
_RESET_FILTER    = build_prefixed_filters("resetwarns") | build_prefixed_filters("clearwarns")

__handlers__ = [
    warn_conversation(),
    MessageHandler(_UNWARN_FILTER,   cmd_unwarn),
    MessageHandler(_WARNLIST_FILTER, cmd_warnlist),
    MessageHandler(_RESET_FILTER,    cmd_resetwarns),
]
