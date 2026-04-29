# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""Feature 27: Welcome and goodbye messages in MAIN_GROUP and EXEC_GROUP only."""
import logging
from html import escape

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from ..config import EXEC_GROUP, MAIN_GROUP
from ..utils.format import safe_first_name, user_link

logger = logging.getLogger(__name__)

WELCOME_GROUPS = {MAIN_GROUP, EXEC_GROUP}


def _welcome_text(group_title: str, user_id: int, first_name: str) -> str:
    return (
        f"<b>Welcome to <i>{escape(group_title)}</i>, "
        f"{user_link(user_id, first_name)}!</b>\n"
        "We're glad to have you here. This is an official group of the Transsion "
        "Core Federation. Please take a moment to review the group rules and feel "
        "free to introduce yourself.\n\n"
        "If you have any questions or need assistance, don't hesitate to ask our admins.\n\n"
        "Enjoy your stay!"
    )


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
        kb = InlineKeyboardMarkup(
            [[InlineKeyboardButton("What is TCF?", url=about_url)]]
        )
        try:
            await msg.reply_text(
                _welcome_text(title, member.id, safe_first_name(member)),
                parse_mode=ParseMode.HTML,
                reply_markup=kb,
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
    try:
        await msg.reply_text(
            f"{user_link(left.id, safe_first_name(left))} has left the group. "
            "We're sad to see you go! If you ever wish to rejoin, you're always welcome back.",
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except TelegramError as exc:
        logger.warning(
            "Failed to send goodbye in %s: %s", msg.chat.id, exc
        )
