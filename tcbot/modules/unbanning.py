# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""Federation unban command."""
from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes, MessageHandler

from tcbot.modules.helper import decorators, extraction
from tcbot.modules.helper.workflows.unban_flow import execute_unban
from tcbot.utils.prefixes import build_prefixed_filters, parse_cmd_args

__module_name__ = "Unban"
__help_text__ = (
    "<code>/tcunban</code> <i>&lt;target&gt;</i> – lift a federation ban.\n"
    "Aliases: <code>/funban</code>, <code>/unban</code>, <code>/tcfunban</code>"
)


@decorators.staff_only
async def cmd_unban(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    args = parse_cmd_args(update.effective_message.text)
    target_id, target_fname = await extraction.extract_target(update, args, ctx.bot)
    if not target_id:
        await update.effective_message.reply_text(
            "Specify a target – reply to a message or provide a user ID."
        )
        return
    await execute_unban(update, ctx, target_id, target_fname)


_FILTER = (
    build_prefixed_filters("tcunban")
    | build_prefixed_filters("funban")
    | build_prefixed_filters("unban")
    | build_prefixed_filters("tcfunban")
)

__handlers__ = [MessageHandler(_FILTER, cmd_unban)]
