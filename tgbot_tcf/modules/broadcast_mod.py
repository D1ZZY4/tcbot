# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""Broadcast business logic.

The :mod:`tgbot_tcf.handlers.broadcast` handler validates input and writes
the audit log; the actual loop over every active federated group lives here
so the per-group Telegram failures can be handled in one well-defined place.
"""
from __future__ import annotations

import logging
from typing import Tuple

from telegram.error import TelegramError
from telegram.ext import ContextTypes

from ..database import groups_repo

logger = logging.getLogger(__name__)


async def broadcast_to_active_groups(
    context: ContextTypes.DEFAULT_TYPE, text: str
) -> Tuple[int, int]:
    """Send ``text`` to every active federated group.

    Groups where the send fails are marked inactive (Telegram has told us
    the bot is no longer reachable). Returns ``(success, failure)``.
    """
    success = 0
    failure = 0
    async for grp in groups_repo.iter_active():
        chat_id = grp["chat_id"]
        try:
            await context.bot.send_message(chat_id=chat_id, text=text)
            success += 1
        except TelegramError as exc:
            failure += 1
            logger.warning("Broadcast to %s failed: %s", chat_id, exc)
            await groups_repo.deactivate(chat_id)
    return success, failure
