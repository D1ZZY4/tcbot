# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""User-facing ban status queries: /checkme and /baninfo."""
import logging

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from ..modules import bans, keyboards
from ..modules.messages import M
from ..utils.format import fmt_dt, user_link
from ..utils.users import resolve_identity
from .helper import targets

logger = logging.getLogger(__name__)


async def cmd_checkme(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Report the calling user's own ban status."""
    msg = update.effective_message
    user = update.effective_user
    if msg is None or user is None:
        return

    record = await bans.find_active_for_user(user.id)
    if record is None:
        await msg.reply_text(M.NOT_BANNED_SELF)
        return

    admin_name = (
        await resolve_identity(context, record["admin_user_id"])
    ).display_name
    me = await context.bot.get_me()
    appeal_url = f"https://t.me/{me.username}?start=appeal_{record['ban_id']}"

    await msg.reply_text(
        M.CHECKME_BANNED.format(reason=record["reason"], admin_name=admin_name),
        reply_markup=keyboards.submit_appeal(appeal_url),
    )


async def cmd_baninfo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show detailed ban information for a target user."""
    msg = update.effective_message
    if msg is None:
        return

    target = await targets.resolve_or_complain(update, context, msg)
    if target is None:
        return

    record = await bans.find_active_for_user(target.id)
    if record is None:
        await msg.reply_text(M.USER_NOT_BANNED_TCF)
        return

    admin_id = record["admin_user_id"]
    admin_name = (await resolve_identity(context, admin_id)).display_name

    text = (
        f"{M.BANINFO_HEADER}\n"
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

    await msg.reply_text(
        text,
        reply_markup=keyboards.view_proof(bans.proof_link_for(record["proof_message_id"])),
        parse_mode=ParseMode.HTML,
    )
