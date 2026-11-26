# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Rich message sending through Kurigram's native MTProto transport."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pyrogram.types import ReplyParameters

from tcbot.modules.helper.rich.block import (
    _input_rich,
    _message_with_buttons,
    html_message,
)
from tcbot.utils.logger import get_logger

if TYPE_CHECKING:
    from pyrogram import Client
    from pyrogram.types import Message

log = get_logger(__name__)


async def send_rich(
    bot: Client,
    chat_id: int | str,
    message: dict[str, object],
    *,
    reply_markup: Any | None = None,
    message_thread_id: int | None = None,
    disable_notification: bool | None = None,
    reply_to_message_id: int | None = None,
    parse_mode: Any = None,
) -> Message:
    """Send a rich message through Kurigram's native MTProto transport."""
    _ = parse_mode
    payload, fallback = _message_with_buttons(message, reply_markup)
    extra: dict[str, Any] = {}
    if fallback is not None:
        extra["reply_markup"] = fallback
    sent = await bot.send_rich_message(
        chat_id,
        _input_rich(payload),
        message_thread_id=message_thread_id,
        disable_notification=disable_notification,
        reply_parameters=(
            ReplyParameters(message_id=reply_to_message_id)
            if reply_to_message_id is not None
            else None
        ),
        **extra,
    )
    if sent is None:
        raise RuntimeError("Telegram returned no message for the rich send")
    return sent


async def send_text(
    bot: Client,
    chat_id: int | str,
    text: str,
    *,
    reply_markup: Any | None = None,
    message_thread_id: int | None = None,
    parse_mode: Any = None,
) -> Message:
    """Send text as a rich message, keeping the transport decision here."""
    return await send_rich(
        bot,
        chat_id,
        html_message(text),
        reply_markup=reply_markup,
        message_thread_id=message_thread_id,
    )


__all__ = ["send_rich", "send_text"]
