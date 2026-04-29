# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""Broadcast handler (PROMPT Feature 12)."""
import logging

from telegram import Update
from telegram.ext import ContextTypes

from ..modules import broadcast_mod, log_templates
from ..modules.messages import M
from ..utils.format import safe_first_name
from ..utils.logger import log_to_channel
from .helper import auth

logger = logging.getLogger(__name__)


async def cmd_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a plain text message to every active federated group."""
    msg = update.effective_message
    user = update.effective_user
    if msg is None or user is None:
        return

    if not await auth.require_authorized(msg, user.id):
        return

    text = " ".join(context.args or []).strip()
    if not text and msg.reply_to_message and msg.reply_to_message.text:
        text = msg.reply_to_message.text
    if not text:
        await msg.reply_text(M.PROVIDE_BROADCAST_TEXT)
        return

    success, failure = await broadcast_mod.broadcast_to_active_groups(context, text)

    await msg.reply_text(
        M.BROADCAST_RESULT.format(success=success, failure=failure)
    )
    await log_to_channel(
        context,
        log_templates.broadcast_log(
            admin_id=user.id,
            admin_name=safe_first_name(user),
            text=text,
            success=success,
            failure=failure,
        ),
    )
