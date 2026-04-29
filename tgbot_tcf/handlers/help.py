# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""/start, /help, and /commands handlers.

* ``/start appeal_<ban_id>`` opens the appeal flow.
* ``/start about`` shows the About TCF text.
* ``/start`` (no args, PM) opens the interactive start menu.
* ``/start`` (no args, group) points the user to PM.
* ``/help`` and ``/commands`` open the interactive help module list.
"""
import logging

from telegram import Update
from telegram.constants import ChatType, ParseMode
from telegram.ext import ContextTypes

from .. import ABOUT_TEXT
from ..modules.messages import M
from .appeal import start_appeal
from .menu import send_help_command, send_start_menu

logger = logging.getLogger(__name__)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    if msg is None:
        return
    args = context.args or []

    if args:
        first = args[0]
        if first.startswith("appeal_"):
            await start_appeal(update, context, first[len("appeal_"):])
            return
        if first == "about":
            await msg.reply_text(
                ABOUT_TEXT,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
            return

    if msg.chat.type == ChatType.PRIVATE:
        await send_start_menu(update, context)
        return

    me = await context.bot.get_me()
    await msg.reply_text(
        M.START_GROUP_HINT.format(username=me.username),
        disable_web_page_preview=True,
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show the interactive help module list."""
    await send_help_command(update, context)
