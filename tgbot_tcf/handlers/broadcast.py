# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""Broadcast a message to all active federated groups."""
import logging

from telegram import Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from .. import BRANDING
from ..database import federated_groups
from ..utils.auth import is_authorized
from ..utils.format import fmt_now, safe_first_name, user_link
from ..utils.logger import log_to_channel

logger = logging.getLogger(__name__)


async def cmd_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a plain text message to all active federated groups."""
    msg = update.effective_message
    user = update.effective_user
    if msg is None or user is None:
        return

    if not await is_authorized(user.id):
        await msg.reply_text("You are not authorized.")
        return

    text = " ".join(context.args or []).strip()
    if not text and msg.reply_to_message and msg.reply_to_message.text:
        text = msg.reply_to_message.text
    if not text:
        await msg.reply_text("Please provide a message to broadcast.")
        return

    success = 0
    failure = 0
    cursor = federated_groups.find({"is_active": True})
    async for grp in cursor:
        try:
            await context.bot.send_message(chat_id=grp["chat_id"], text=text)
            success += 1
        except TelegramError as exc:
            failure += 1
            logger.warning("Broadcast to %s failed: %s", grp["chat_id"], exc)
            await federated_groups.update_one(
                {"chat_id": grp["chat_id"]}, {"$set": {"is_active": False}}
            )

    await msg.reply_text(
        f"Broadcast sent to {success} groups. Failed: {failure} groups."
    )
    await log_to_channel(
        context,
        "<b>Broadcast Sent</b>\n"
        f"{BRANDING}\n"
        f"Admin: {user_link(user.id, safe_first_name(user))}\n"
        f"Message: {text[:100]}\n"
        f"Groups reached: {success}\n"
        f"Failed groups: {failure}\n"
        f"Date: {fmt_now()}",
    )
