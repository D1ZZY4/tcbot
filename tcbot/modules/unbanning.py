# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""Federation unban command."""
from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes, MessageHandler

from tcbot import database as db
from tcbot.modules.helper import decorators, extraction
from tcbot.modules.helper.workflows.unban_flow import execute_unban
from tcbot.utils.prefixes import build_prefixed_filters, parse_cmd_args

__module_name__ = "Unban"
__help_text__ = (
    "<b>Commands & Aliases</b>\n"
    "<code>/tcunban</code> (alias: <code>/tcunb</code>)\n\n"

    "<b>Who can use it</b>\n"
    "Developer and above (Founder / Admin / Developer).\n\n"

    "<b>Where to use it</b>\n"
    "Exec group, connected groups, or bot PM.\n\n"

    "<b>What it does</b>\n"
    "Lifts an active federation ban on the target user. The unban is applied across "
    "all connected groups automatically, and a log entry is posted to the logs channel.\n"
    "If the user has no active ban, the bot will let you know.\n\n"

    "<b>How to specify the target</b>\n"
    "Reply to a message, or provide a user ID / @username.\n\n"

    "<b>Examples</b>\n"
    "<code>/tcunban @username</code>\n"
    "<code>/tcunb 123456789</code>\n"
    "Or reply to a message and run <code>/tcunb</code>."
)


@decorators.mod_only
async def cmd_unban(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    args = parse_cmd_args(update.effective_message.text)
    target_id, target_fname = await extraction.extract_target(update, args, ctx.bot)
    if not target_id:
        await update.effective_message.reply_text(
            "Specify a target — reply to a message or provide a user ID."
        )
        return
    if target_id == ctx.bot.id:
        await update.effective_message.reply_text("That's me — not banned anywhere. Nothing to undo.")
        return
    if await db.admins_db.is_owner(target_id):
        await update.effective_message.reply_text("That's the Founder — never been banned, nothing to undo.")
        return
    await execute_unban(update, ctx, target_id, target_fname)


_FILTER = (
    build_prefixed_filters("tcunban")
    | build_prefixed_filters("tcunb")
)

__handlers__ = [MessageHandler(_FILTER, cmd_unban)]
