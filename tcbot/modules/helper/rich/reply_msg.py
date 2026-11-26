# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Rich replies through Kurigram's bound reply transport."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from tcbot.modules.helper.rich.block import (
    _input_rich,
    _message_with_buttons,
    html_message,
)
from tcbot.utils.dispatch import is_edit_target_gone_error
from tcbot.utils.logger import get_logger

if TYPE_CHECKING:
    from pyrogram.types import Message

log = get_logger(__name__)


async def reply_rich_result(
    msg: Message,
    text: str,
    *,
    reply_markup: Any | None = None,
    disable_notification: bool | None = None,
) -> Message:
    """Rich reply that returns the sent message so flows can record its id."""
    payload, fallback = _message_with_buttons(html_message(text), reply_markup)
    extra: dict[str, Any] = {}
    if fallback is not None:
        extra["reply_markup"] = fallback
    sent = await msg.reply_rich(
        _input_rich(payload),
        disable_notification=disable_notification,
        **extra,
    )
    if sent is None:
        raise RuntimeError("Telegram returned no message for the rich reply")
    return sent


async def reply_rich(
    msg: Message,
    text: str,
    *,
    log_label: str = "reply",
    parse_mode: Any = None,
    **kwargs: Any,
) -> None:
    """Send a rich reply, logging a transport failure instead of raising."""
    _ = parse_mode
    markup = kwargs.get("reply_markup")
    payload, fallback = _message_with_buttons(html_message(text), markup)
    extra: dict[str, Any] = {}
    if fallback is not None:
        extra["reply_markup"] = fallback
    try:
        await msg.reply_rich(
            _input_rich(payload),
            disable_notification=kwargs.get("disable_notification"),
            **extra,
        )
    except Exception as exc:
        if is_edit_target_gone_error(exc):
            log.debug("%s reply skipped: %s", log_label, exc)
        else:
            log.warning("%s reply failed: %s", log_label, exc)


__all__ = ["reply_rich", "reply_rich_result"]
