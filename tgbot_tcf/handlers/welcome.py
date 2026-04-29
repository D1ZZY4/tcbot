# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""Welcome / goodbye messages in MAIN_GROUP and EXEC_GROUP (Feature 27)."""
import logging
from html import escape

from telegram import Update
from telegram.constants import ParseMode
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from .. import EXEC_GROUP, MAIN_GROUP
from ..modules import keyboards
from ..modules.messages import M
from ..utils.format import safe_first_name, user_link

logger = logging.getLogger(__name__)

WELCOME_GROUPS = {MAIN_GROUP, EXEC_GROUP}


async def on_member_join(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a welcome message when a user joins MAIN_GROUP or EXEC_GROUP."""
    msg = update.effective_message
    if msg is None or msg.chat.id not in WELCOME_GROUPS:
        return
    members = msg.new_chat_members or []
    if not members:
        return
    bot_id = context.bot.id
    title = msg.chat.title or ""

    me = await context.bot.get_me()
    about_url = f"https://t.me/{me.username}?start=about"

    for member in members:
        if member.id == bot_id:
            continue
        link = user_link(member.id, safe_first_name(member))
        try:
            await msg.reply_text(
                M.WELCOME_GROUP.format(
                    group_title=escape(title), user_link=link
                ),
                parse_mode=ParseMode.HTML,
                reply_markup=keyboards.what_is_tcf(about_url),
                disable_web_page_preview=True,
            )
        except TelegramError as exc:
            logger.warning(
                "Failed to send welcome in %s: %s", msg.chat.id, exc
            )


async def on_member_left(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a goodbye message when a user leaves MAIN_GROUP or EXEC_GROUP."""
    msg = update.effective_message
    if msg is None or msg.chat.id not in WELCOME_GROUPS:
        return
    left = msg.left_chat_member
    if left is None or left.id == context.bot.id:
        return
    link = user_link(left.id, safe_first_name(left))
    try:
        await msg.reply_text(
            M.GOODBYE_GROUP.format(user_link=link),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except TelegramError as exc:
        logger.warning(
            "Failed to send goodbye in %s: %s", msg.chat.id, exc
        )
