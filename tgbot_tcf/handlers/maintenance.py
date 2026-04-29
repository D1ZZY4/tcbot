# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""Maintenance commands: /leaveall and /cleanup."""
import logging

from telegram import Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from .. import BRANDING
from ..database import federated_groups
from ..utils.auth import is_authorized, is_tc_owner
from ..utils.format import fmt_now, safe_first_name, user_link
from ..utils.logger import log_to_channel

logger = logging.getLogger(__name__)


async def cmd_leaveall(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Leave every active federated group. TC owner only."""
    msg = update.effective_message
    user = update.effective_user
    if msg is None or user is None:
        return

    if not await is_tc_owner(user.id):
        await msg.reply_text("You are not authorized.")
        return

    success = 0
    failure = 0
    cursor = federated_groups.find({"is_active": True})
    groups = [g async for g in cursor]

    for g in groups:
        chat_id = g["chat_id"]
        title = g.get("title") or str(chat_id)
        try:
            await context.bot.leave_chat(chat_id)
            await federated_groups.update_one(
                {"chat_id": chat_id}, {"$set": {"is_active": False}}
            )
            success += 1
            await log_to_channel(
                context,
                "<b>Group Disaffiliated</b>\n"
                f"{BRANDING}\n"
                f"Group: {title} (ID: {chat_id})\n"
                f"Removed by: {user_link(user.id, safe_first_name(user))} (ID: {user.id})\n"
                f"Date: {fmt_now()}",
            )
        except TelegramError as exc:
            failure += 1
            logger.warning("Leave %s failed: %s", chat_id, exc)

    await msg.reply_text(
        f"Left {success} groups. Failed to leave {failure} groups."
    )


async def cmd_cleanup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Mark inaccessible affiliated groups as inactive. TC owner/admins."""
    msg = update.effective_message
    user = update.effective_user
    if msg is None or user is None:
        return

    if not await is_authorized(user.id):
        await msg.reply_text("You are not authorized.")
        return

    cleaned = 0
    cursor = federated_groups.find({"is_active": True})
    groups = [g async for g in cursor]

    for g in groups:
        chat_id = g["chat_id"]
        title = g.get("title") or str(chat_id)
        accessible = True
        try:
            me = await context.bot.get_chat_member(chat_id, context.bot.id)
            if me.status in ("left", "kicked"):
                accessible = False
        except TelegramError:
            accessible = False

        if not accessible:
            await federated_groups.update_one(
                {"chat_id": chat_id}, {"$set": {"is_active": False}}
            )
            cleaned += 1
            await log_to_channel(
                context,
                "<b>Group Disaffiliated</b>\n"
                f"{BRANDING}\n"
                f"Group: {title} (ID: {chat_id})\n"
                f"Removed by: {user_link(user.id, safe_first_name(user))} (ID: {user.id})\n"
                f"Date: {fmt_now()}",
            )

    await msg.reply_text(
        f"Cleaned up {cleaned} groups that were no longer accessible."
    )
