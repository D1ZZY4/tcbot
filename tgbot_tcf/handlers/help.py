"""/start, /help, /commands handlers.

- /start <appeal_xxx> - opens the appeal flow (Feature 8 entry).
- /start about        - sends the static About TCF text (Feature 17).
- /start (no args)    - opens the interactive start menu (Feature 24).
- /help, /commands    - opens the interactive help system (Feature 19).
"""
import logging

from telegram import Update
from telegram.constants import ChatType
from telegram.ext import ContextTypes

from ..config import ABOUT_TEXT
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
            await msg.reply_text(ABOUT_TEXT, disable_web_page_preview=True)
            return

    if msg.chat.type == ChatType.PRIVATE:
        await send_start_menu(update, context)
        return

    # In a group, just point users to PM for the menu.
    me = await context.bot.get_me()
    await msg.reply_text(
        "Open a private chat with me and send /start to see the menu, "
        f"or use /help here.\nBot: @{me.username}",
        disable_web_page_preview=True,
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await send_help_command(update, context)
