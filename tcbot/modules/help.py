# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""Help command module – redirects to the help system in start.py."""
from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes, MessageHandler

from tcbot.modules.helper import keyboards
from tcbot.utils.prefixes import build_prefixed_filters

__module_name__ = None


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(
        "<b>TCF Bot Help</b>\n"
        "I manage Transsion Core groups, bans, appeals, and more. Select a topic below:",
        parse_mode="HTML",
        reply_markup=keyboards.help_topics_kb(),
    )


_HELP_FILTER = (
    build_prefixed_filters("help")
    | build_prefixed_filters("commands")
)

__handlers__ = [
    MessageHandler(_HELP_FILTER, cmd_help),
]
