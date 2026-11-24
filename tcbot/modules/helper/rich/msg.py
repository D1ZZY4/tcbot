# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Rich message sending: ``send_rich`` and ``reply_rich``.

Owns the rich message payloads and the Kurigram-native transport. Kurigram
exposes Telegram rich messages directly through ``InputRichMessage``, so the
HTML produced by the formatting helpers is sent verbatim. Inline keyboards
stay as real ``pyrogram.types.InlineKeyboardMarkup`` objects. Editing lives in
``rich.edit``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pyrogram.types import InputRichMessage, ReplyParameters

from tcbot.modules.helper.rich.button import buttons_from_markup
from tcbot.modules.helper.rich.formats import divider
from tcbot.utils.logger import get_logger

if TYPE_CHECKING:
    from pyrogram import Client
    from pyrogram.types import Message

log = get_logger(__name__)


# ───────────────────────────── Message assembly ───────────────────────── #


def html_message(
    *blocks: str, rtl: bool = False, skip_entity_detection: bool = False
) -> dict[str, Any]:
    """Build a rich message payload keyed by HTML content."""
    payload: dict[str, Any] = {"html": "\n".join(b for b in blocks if b)}
    if rtl:
        payload["is_rtl"] = True
    if skip_entity_detection:
        payload["skip_entity_detection"] = True
    return payload


def blocks_message(blocks: list[dict[str, Any]]) -> dict[str, Any]:
    """Build a rich message payload from explicit block objects."""
    return {"blocks": blocks}


def _message_with_buttons(
    message: dict[str, Any], reply_markup: Any | None
) -> tuple[dict[str, Any], bool]:
    """Append rich button rows to an HTML payload when they can be expressed."""
    rows = buttons_from_markup(reply_markup)
    html_value = message.get("html")
    if not rows or not isinstance(html_value, str):
        return message, False
    payload = dict(message)
    separator = [] if html_value.rstrip().endswith("<hr/>") else [divider()]
    payload["html"] = "\n".join([html_value, *separator, *rows])
    return payload, True


def _input_rich(message: dict[str, Any]) -> InputRichMessage:
    """Convert an application rich payload into Kurigram's native payload."""
    kwargs: dict[str, Any] = {}
    if "html" in message:
        kwargs["html"] = message["html"]
    elif "blocks" in message:
        kwargs["blocks"] = message["blocks"]
    if message.get("is_rtl"):
        kwargs["is_rtl"] = True
    if message.get("skip_entity_detection"):
        kwargs["skip_entity_detection"] = True
    return InputRichMessage(**kwargs)


# ───────────────────────────── Transport ──────────────────────────────── #


async def send_rich(
    bot: Client,
    chat_id: int | str,
    message: dict[str, Any],
    *,
    reply_markup: Any | None = None,
    message_thread_id: int | None = None,
    disable_notification: bool | None = None,
    reply_to_message_id: int | None = None,
) -> Message:
    """Send a rich message through Kurigram's native MTProto transport."""
    payload, _embedded = _message_with_buttons(message, reply_markup)
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
) -> Message:
    """Send text as a rich message, keeping the decision at this boundary."""
    return await send_rich(
        bot,
        chat_id,
        html_message(text),
        reply_markup=reply_markup,
        message_thread_id=message_thread_id,
    )


async def reply_rich_result(
    msg: Message,
    text: str,
    *,
    reply_markup: Any | None = None,
    disable_notification: bool | None = None,
) -> Message:
    """Rich reply that returns the sent message so flows can record its id.

    Kurigram's bound ``reply_rich`` forwards the host message's thread id; it
    has no ``message_thread_id`` parameter of its own.
    """
    payload, _embedded = _message_with_buttons(html_message(text), reply_markup)
    sent = await msg.reply_rich(
        _input_rich(payload),
        disable_notification=disable_notification,
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
    """Send a rich reply; transport errors propagate to the caller's guard.

    ``message_thread_id`` stays accepted for call-site compatibility but the
    bound Kurigram reply already carries the host message's thread id.
    """
    _ = parse_mode
    markup = kwargs.get("reply_markup")
    payload, _embedded = _message_with_buttons(html_message(text), markup)
    try:
        await msg.reply_rich(
            _input_rich(payload),
            disable_notification=kwargs.get("disable_notification"),
        )
    except Exception as exc:
        detail = str(exc).lower()
        if any(
            marker in detail
            for marker in ("chat not found", "message to edit not found", "too old")
        ):
            log.debug("%s reply skipped: %s", log_label, exc)
        else:
            log.warning("%s reply failed: %s", log_label, exc)


__all__ = [
    "blocks_message",
    "html_message",
    "reply_rich",
    "reply_rich_result",
    "send_rich",
    "send_text",
]
