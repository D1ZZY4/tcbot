# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""User-facing ban status queries: /checkme and /baninfo."""
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from ..database import bans
from ..utils.format import fmt_dt, topic_link, user_link
from ..utils.targets import resolve_target
from .. import MAIN_GROUP, PROOF_TOPIC

logger = logging.getLogger(__name__)


async def cmd_checkme(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Report the calling user's own ban status."""
    msg = update.effective_message
    user = update.effective_user
    if msg is None or user is None:
        return

    record = await bans.find_one({"banned_user_id": user.id, "is_active": True})
    if not record:
        await msg.reply_text("You are not banned in the Transsion Core.")
        return

    admin_id = record["admin_user_id"]
    try:
        admin = await context.bot.get_chat(admin_id)
        admin_name = admin.first_name or str(admin_id)
    except TelegramError:
        admin_name = str(admin_id)

    me = await context.bot.get_me()
    appeal_url = f"https://t.me/{me.username}?start=appeal_{record['ban_id']}"
    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton("Submit Appeal", url=appeal_url)]]
    )
    text = (
        "You are currently banned from Transsion Core.\n"
        f"Reason: {record['reason']}\n"
        f"Banned by Transsion Core Admin: {admin_name}"
    )
    await msg.reply_text(text, reply_markup=keyboard)


async def cmd_baninfo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show detailed ban information for a target user."""
    msg = update.effective_message
    if msg is None:
        return

    target = await resolve_target(update, context)
    if target is None:
        await msg.reply_text("Cannot resolve user.")
        return

    record = await bans.find_one({"banned_user_id": target.id, "is_active": True})
    if not record:
        await msg.reply_text("User is not banned in the Transsion Core.")
        return

    admin_id = record["admin_user_id"]
    try:
        admin = await context.bot.get_chat(admin_id)
        admin_name = admin.first_name or str(admin_id)
    except TelegramError:
        admin_name = str(admin_id)

    text = (
        "<b>Ban Details</b>\n"
        f"User: {user_link(target.id, target.first_name)}\n"
        f"User ID: {target.id}\n"
        f"Reason: {record['reason']}\n"
        f"Banned by: {user_link(admin_id, admin_name)}\n"
        f"Date: {fmt_dt(record['timestamp'])}\n"
        f"Ban ID: {record['ban_id']}\n"
        "Status: Active"
    )
    if record.get("update_count", 0) > 0 and record.get("updated_timestamp"):
        text += f"\nLast Updated: {fmt_dt(record['updated_timestamp'])}"

    proof_link = topic_link(MAIN_GROUP, record["proof_message_id"], PROOF_TOPIC)
    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton("View Proof", url=proof_link)]]
    )
    await msg.reply_text(
        text, reply_markup=keyboard, parse_mode=ParseMode.HTML
    )
