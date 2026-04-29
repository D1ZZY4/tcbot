"""Feature 27: Welcome and goodbye messages, only in MAIN_GROUP and EXEC_GROUP.

These run in a separate handler group from the affiliation prompt so both
can react to the same NEW_CHAT_MEMBERS update without interfering.
"""
import logging
from html import escape

from telegram import Update
from telegram.constants import ParseMode
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from ..config import EXEC_GROUP, MAIN_GROUP
from ..utils.format import safe_first_name, user_link

logger = logging.getLogger(__name__)


WELCOME_GROUPS = {MAIN_GROUP, EXEC_GROUP}


def _welcome_text(group_title: str, user_id: int, first_name: str) -> str:
    return (
        f"Welcome to <b>{escape(group_title)}</b>, "
        f"{user_link(user_id, first_name)}!\n"
        "This is an official group of Transsion Core Federation (TCF). "
        "Please respect the rules and enjoy your stay.\n\n"
        "If you know someone who has the skills, potential, or a strong "
        "determination to contribute to the development of Transsion devices, "
        "feel free to invite them to TRAVEL - Transsion Holding's Development "
        "(unofficial community).\n"
        "Join TRAVEL: http://t.me/+S2C_ppFvHlAwMzNl"
    )


async def on_member_join(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    if msg is None or msg.chat.id not in WELCOME_GROUPS:
        return
    members = msg.new_chat_members or []
    if not members:
        return
    bot_id = context.bot.id
    title = msg.chat.title or ""
    for member in members:
        if member.id == bot_id:
            continue
        try:
            await msg.reply_text(
                _welcome_text(title, member.id, safe_first_name(member)),
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
        except TelegramError as exc:
            logger.warning("Failed to send welcome in %s: %s", msg.chat.id, exc)


async def on_member_left(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    if msg is None or msg.chat.id not in WELCOME_GROUPS:
        return
    left = msg.left_chat_member
    if left is None or left.id == context.bot.id:
        return
    try:
        await msg.reply_text(
            f"{user_link(left.id, safe_first_name(left))} has left. Goodbye!",
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except TelegramError as exc:
        logger.warning("Failed to send goodbye in %s: %s", msg.chat.id, exc)
