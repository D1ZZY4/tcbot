# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""Telegram-API wrappers that swallow common errors gracefully.

Editing a previously-sent prompt to show the result of an operation is a
common pattern in this bot. These helpers wrap the ``TelegramError`` that
arises when the original message is gone so handler code stays clean.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from telegram import InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.error import TelegramError
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)


async def safe_edit_text(
    context: ContextTypes.DEFAULT_TYPE,
    *,
    chat_id: int,
    message_id: int,
    text: str,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
    parse_mode: Any = ParseMode.HTML,
    disable_web_page_preview: bool = True,
) -> bool:
    """Edit ``message_id`` and return ``True`` on success."""
    try:
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
            disable_web_page_preview=disable_web_page_preview,
        )
        return True
    except TelegramError as exc:
        logger.debug("safe_edit_text suppressed: %s", exc)
        return False


async def safe_edit_callback(
    cq: Any,
    text: str,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
    parse_mode: Any = ParseMode.HTML,
) -> bool:
    """Edit a callback-query message; swallow Telegram errors."""
    try:
        await cq.edit_message_text(
            text,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
            disable_web_page_preview=True,
        )
        return True
    except TelegramError as exc:
        logger.debug("safe_edit_callback suppressed: %s", exc)
        return False


async def safe_send_dm(
    context: ContextTypes.DEFAULT_TYPE,
    *,
    user_id: int,
    text: str,
    parse_mode: Any = None,
) -> bool:
    """Send a direct message; ``False`` if the user blocks the bot or similar."""
    try:
        await context.bot.send_message(
            chat_id=user_id, text=text, parse_mode=parse_mode
        )
        return True
    except TelegramError as exc:
        logger.debug("safe_send_dm suppressed: %s", exc)
        return False


async def fetch_display_name(
    context: ContextTypes.DEFAULT_TYPE, user_id: int
) -> str:
    """Look up ``user_id`` and return a sensible display name."""
    try:
        chat = await context.bot.get_chat(user_id)
        return chat.first_name or chat.title or str(user_id)
    except TelegramError:
        return str(user_id)
