# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""Force-sync a Transsion Core ban across all federated groups."""
import logging

from telegram import Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from .. import BRANDING
from ..database import bans, federated_groups
from ..utils.auth import is_authorized
from ..utils.format import fmt_now, safe_first_name, user_link
from ..utils.logger import log_to_channel
from ..utils.targets import resolve_target

logger = logging.getLogger(__name__)


async def cmd_syncban(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Enforce an active ban across all federated groups."""
    msg = update.effective_message
    user = update.effective_user
    if msg is None or user is None:
        return

    if not await is_authorized(user.id):
        await msg.reply_text("You are not authorized.")
        return

    target = await resolve_target(update, context)
    if target is None:
        await msg.reply_text("Cannot resolve user.")
        return

    record = await bans.find_one({"banned_user_id": target.id, "is_active": True})
    if not record:
        await msg.reply_text("User is not banned in the Transsion Core.")
        return

    success = 0
    failure = 0
    cursor = federated_groups.find({"is_active": True})
    async for grp in cursor:
        chat_id = grp["chat_id"]
        try:
            me = await context.bot.get_chat_member(chat_id, context.bot.id)
            if not getattr(me, "can_restrict_members", False):
                failure += 1
                continue
            await context.bot.ban_chat_member(chat_id=chat_id, user_id=target.id)
            success += 1
        except TelegramError as exc:
            failure += 1
            logger.warning("Sync ban in %s failed: %s", chat_id, exc)

    await msg.reply_text(
        f"Ban enforced across {success} groups. Failed: {failure} groups."
    )
    await log_to_channel(
        context,
        "<b>Ban Synced Across Groups</b>\n"
        f"{BRANDING}\n"
        f"Admin: {user_link(user.id, safe_first_name(user))}\n"
        f"User: {user_link(target.id, target.first_name)} (ID: {target.id})\n"
        f"Groups enforced: {success}\n"
        f"Failures: {failure}\n"
        f"Date: {fmt_now()}",
    )
