# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Rich message sending: ``send_rich`` and ``reply_rich``.

Owns the InputRichMessage payloads, inline-button conversion, and the PTB
``do_api_request`` send transport. Messages are rich only; there is no plain
text or alternate parse-mode send path. Editing lives in ``rich_edit.py``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from tcbot.modules.helper.messages.rich_format import divider
from tcbot.modules.helper.messages.rich_link import _markup_dict, keyboard_rows
from tcbot.utils.logger import get_logger

if TYPE_CHECKING:
    from telegram import Bot, Message

log = get_logger(__name__)


# ───────────────────────────── Message assembly ───────────────────────── #


def html_message(
    *blocks: str, rtl: bool = False, skip_entity_detection: bool = False
) -> dict[str, Any]:
    """Build an ``InputRichMessage`` with HTML content."""
    payload: dict[str, Any] = {"html": "\n".join(b for b in blocks if b)}
    if rtl:
        payload["is_rtl"] = True
    if skip_entity_detection:
        payload["skip_entity_detection"] = True
    return payload


def blocks_message(blocks: list[dict[str, Any]]) -> dict[str, Any]:
    """Build an ``InputRichMessage`` from explicit block objects."""
    return {"blocks": blocks}


def _message_with_buttons(
    message: dict[str, Any], reply_markup: Any | None
) -> tuple[dict[str, Any], bool]:
    """Append rich button rows to an HTML payload."""
    rows = keyboard_rows(reply_markup)
    html_value = message.get("html")
    if not rows or not isinstance(html_value, str):
        return message, False
    payload = dict(message)
    # * A rule separates content from the keyboard so the last line never
    # * sits flush against the buttons. An existing trailing rule is kept.
    separator = [] if html_value.rstrip().endswith("<hr/>") else [divider()]
    payload["html"] = "\n".join([html_value, *separator, *rows])
    return payload, True


# ───────────────────────────── Transport ──────────────────────────────── #


async def send_rich(
    bot: Bot,
    chat_id: int | str,
    message: dict[str, Any],
    *,
    reply_markup: Any | None = None,
    message_thread_id: int | None = None,
    disable_notification: bool | None = None,
    reply_to_message_id: int | None = None,
) -> Message:
    """Send an ``InputRichMessage`` through PTB's Bot API escape hatch."""
    from telegram import Message as MessageType  # noqa: PLC0415 (heavy import on use)

    if not hasattr(bot, "do_api_request"):
        raise RuntimeError("rich send needs a Bot with do_api_request support")

    payload, embedded = _message_with_buttons(message, reply_markup)
    api_kwargs: dict[str, Any] = {"chat_id": chat_id, "rich_message": payload}
    markup = _markup_dict(reply_markup)
    if markup is not None and not embedded:
        api_kwargs["reply_markup"] = markup
    if message_thread_id is not None:
        api_kwargs["message_thread_id"] = message_thread_id
    if disable_notification is not None:
        api_kwargs["disable_notification"] = disable_notification
    if reply_to_message_id is not None:
        api_kwargs["reply_parameters"] = {"message_id": reply_to_message_id}
    return await bot.do_api_request(
        "sendRichMessage", api_kwargs=api_kwargs, return_type=MessageType
    )


async def reply_rich(
    msg: Message,
    text: str,
    *,
    log_label: str = "reply",
    parse_mode: Any = None,
    **kwargs: Any,
) -> None:
    """Send a rich reply. ``parse_mode`` is accepted for call compatibility."""
    from telegram import Bot  # noqa: PLC0415 (heavy import on use)

    _ = parse_mode
    getter = getattr(msg, "get_bot", None)
    rich_bot = getter() if getter is not None else None
    if not isinstance(rich_bot, Bot):
        await msg.reply_text(text, **kwargs)
        return
    try:
        await send_rich(
            rich_bot,
            msg.chat.id,
            html_message(text),
            reply_to_message_id=msg.message_id,
            reply_markup=kwargs.get("reply_markup"),
            message_thread_id=kwargs.get("message_thread_id"),
            disable_notification=kwargs.get("disable_notification"),
        )
    except Exception as exc:
        log.debug("%s reply failed: %s", log_label, exc)


__all__ = [
    "blocks_message",
    "html_message",
    "reply_rich",
    "send_rich",
]
