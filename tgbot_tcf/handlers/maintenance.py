# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""Maintenance handlers: /leaveall (owner-only) and /cleanup (TC-authorized)."""
import logging

from telegram import Update
from telegram.ext import ContextTypes

from ..modules import maintenance_mod
from ..modules.messages import M
from ..utils.format import safe_first_name
from .helper import auth

logger = logging.getLogger(__name__)


async def cmd_leaveall(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Leave every active federated group. TC owner only."""
    msg = update.effective_message
    user = update.effective_user
    if msg is None or user is None:
        return

    if not await auth.require_owner(msg, user.id):
        return

    success, failure = await maintenance_mod.leave_all_active_groups(
        context,
        by_user_id=user.id,
        by_user_name=safe_first_name(user),
    )
    await msg.reply_text(
        M.LEAVE_ALL_RESULT.format(success=success, failure=failure)
    )


async def cmd_cleanup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Mark inaccessible affiliated groups as inactive. TC owner / admins."""
    msg = update.effective_message
    user = update.effective_user
    if msg is None or user is None:
        return

    if not await auth.require_authorized(msg, user.id):
        return

    cleaned = await maintenance_mod.cleanup_inaccessible_groups(
        context,
        by_user_id=user.id,
        by_user_name=safe_first_name(user),
    )
    await msg.reply_text(M.CLEANUP_RESULT.format(count=cleaned))
