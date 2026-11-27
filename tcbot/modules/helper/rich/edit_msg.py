# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Rich message edits, callback answers, and the federation log transport."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from pyrogram.types import InlineKeyboardMarkup

from tcbot import cfg
from tcbot.modules.helper.rich.block import (
    _input_rich,
    _message_with_buttons,
    html_message,
)
from tcbot.modules.helper.rich.send_msg import send_rich
from tcbot.utils.dispatch import (
    is_edit_not_modified_error,
    is_edit_target_gone_error,
    throw_if_cancelled,
)
from tcbot.utils.logger import get_logger

if TYPE_CHECKING:
    from collections.abc import Awaitable

    from pyrogram import Client
    from pyrogram.types import CallbackQuery, Message

log = get_logger(__name__)


async def edit_rich(
    bot: Client,
    chat_id: int | str,
    message_id: int,
    message: dict[str, Any],
    *,
    reply_markup: Any | None = None,
    clear_markup: bool = False,
) -> Message:
    """Edit a message through Kurigram's native rich-message transport."""
    payload, fallback = _message_with_buttons(message, reply_markup)
    extra: dict[str, Any] = {}
    if fallback is not None:
        extra["reply_markup"] = fallback
    if clear_markup:
        extra["reply_markup"] = InlineKeyboardMarkup([])
    return await bot.edit_message_text(
        chat_id,
        message_id,
        rich_message=_input_rich(payload),
        **extra,
    )


def _log_edit_failure(
    level: str, label: str | None, default_msg: str, exc: BaseException
) -> None:
    """Emit an edit-failure line at ``level`` using the call-site ``label``."""
    msg = f"{label} edit failed: %s" if label is not None else default_msg
    getattr(log, level)(msg, exc)


async def _edit_via(
    do_edit: Awaitable[object],
    *,
    log_level: str,
    log_label: str | None,
    catch_all: bool,
    default_msg: str,
) -> bool:
    """Run one edit coroutine with the shared benign-error policy."""
    try:
        await do_edit
        return True
    except Exception as exc:
        if is_edit_not_modified_error(exc):
            return True
        if is_edit_target_gone_error(exc):
            return False
        if not catch_all:
            raise
        _log_edit_failure(log_level, log_label, default_msg, exc)
        return False


async def safe_edit(
    msg: Message,
    text: str,
    *,
    log_level: str = "warning",
    log_label: str | None = None,
    catch_all: bool = False,
    clear_markup: bool = False,
    parse_mode: Any = None,
    **kwargs: Any,
) -> None:
    """Edit a message as a rich message; swallow harmless not-modified errors."""
    _ = parse_mode
    markup = kwargs.get("reply_markup")
    payload, fallback = _message_with_buttons(html_message(text), markup)
    extra: dict[str, Any] = {}
    if fallback is not None:
        extra["reply_markup"] = fallback
    if clear_markup:
        extra["reply_markup"] = InlineKeyboardMarkup([])
    await _edit_via(
        msg.edit_text(rich_message=_input_rich(payload), **extra),
        log_level=log_level,
        log_label=log_label,
        catch_all=catch_all,
        default_msg="edit failed: %s",
    )


async def safe_edit_cb(
    q: CallbackQuery,
    text: str,
    *,
    log_level: str = "warning",
    log_label: str | None = None,
    catch_all: bool = False,
    clear_markup: bool = False,
    parse_mode: Any = None,
    **kwargs: Any,
) -> bool:
    """Edit a callback-query message, returning whether the edit landed."""
    _ = parse_mode
    markup = kwargs.get("reply_markup")
    payload, fallback = _message_with_buttons(html_message(text), markup)
    extra: dict[str, Any] = {}
    if fallback is not None:
        extra["reply_markup"] = fallback
    if clear_markup:
        extra["reply_markup"] = InlineKeyboardMarkup([])
    return await _edit_via(
        q.edit_message_text(rich_message=_input_rich(payload), **extra),
        log_level=log_level,
        log_label=log_label,
        catch_all=catch_all,
        default_msg="callback edit failed: %s",
    )


async def safe_edit_message(
    bot: Client,
    chat_id: int | None,
    message_id: int | None,
    text: str,
    *,
    log_level: str = "warning",
    log_label: str | None = None,
    catch_all: bool = False,
    clear_markup: bool = False,
    parse_mode: Any = None,
    **kwargs: Any,
) -> bool:
    """Edit a message by chat/message ID, returning whether it landed."""
    _ = parse_mode
    if chat_id is None or message_id is None:
        return False
    markup = kwargs.get("reply_markup")
    payload, fallback = _message_with_buttons(html_message(text), markup)
    extra: dict[str, Any] = {}
    if fallback is not None:
        extra["reply_markup"] = fallback
    if clear_markup:
        extra["reply_markup"] = InlineKeyboardMarkup([])
    return await _edit_via(
        bot.edit_message_text(
            chat_id, message_id, rich_message=_input_rich(payload), **extra
        ),
        log_level=log_level,
        log_label=log_label,
        catch_all=catch_all,
        default_msg="message edit failed: %s",
    )


async def clear_markup(bot: Client, chat_id: int | str, message_id: int) -> None:
    """Remove the inline keyboard from a message identified by chat and id."""
    try:
        await bot.edit_message_reply_markup(
            chat_id=chat_id,
            message_id=message_id,
            reply_markup=InlineKeyboardMarkup([]),
        )
    except Exception as exc:
        if is_edit_target_gone_error(exc) or is_edit_not_modified_error(exc):
            return
        log.warning("clear markup failed: %s", exc)


async def clear_markup_cb(q: CallbackQuery) -> None:
    """Remove the inline keyboard from a callback-query message."""
    try:
        await q.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup([]))
    except Exception as exc:
        if is_edit_target_gone_error(exc) or is_edit_not_modified_error(exc):
            return
        log.warning("clear markup failed: %s", exc)


async def answer_alert(q: CallbackQuery, text: str) -> None:
    """Answer a callback query with a plain alert; never raises."""
    try:
        await q.answer(text, show_alert=True)
    except Exception as exc:
        log.debug("callback alert answer failed: %s", exc)


async def answer_ack(q: CallbackQuery) -> None:
    """Acknowledge a callback query without a message; never raises."""
    try:
        await q.answer()
    except Exception as exc:
        log.debug("callback ack failed: %s", exc)


async def answer_and_edit(q: CallbackQuery, text: str, **kwargs: Any) -> None:
    """Answer a callback query and edit its message in parallel."""
    answer_r, edit_r = await asyncio.gather(
        answer_ack(q), safe_edit_cb(q, text, **kwargs), return_exceptions=True
    )
    throw_if_cancelled((answer_r, edit_r))
    if isinstance(answer_r, BaseException):
        log.debug("answer_and_edit answer failed: %s", answer_r)
    if isinstance(edit_r, BaseException):
        log.warning("answer_and_edit edit failed: %s", edit_r)


async def ack_and_render(
    q: CallbackQuery,
    data_coro: Awaitable[tuple[str, InlineKeyboardMarkup | None]],
    *,
    fallback: tuple[str, InlineKeyboardMarkup | None] | None = None,
) -> None:
    """Acknowledge the callback query and run the data coroutine in parallel.

    A failed render leaves the panel unchanged. A caller that can supply a
    localized error card passes it as *fallback*; callers without one keep the
    existing silent behavior.
    """
    ans, result = await asyncio.gather(answer_ack(q), data_coro, return_exceptions=True)
    throw_if_cancelled((ans, result))
    if isinstance(result, BaseException):
        log.error("ack_and_render data fetch failed: %s", result)
        if fallback is not None:
            error_text, error_btn = fallback
            await safe_edit_cb(
                q,
                error_text,
                reply_markup=error_btn,
                log_level="debug",
                log_label="ack_and_render fallback",
                catch_all=True,
            )
        return
    text, btn = result
    await safe_edit_cb(q, text, reply_markup=btn)


def callback_text(data: str | bytes | None) -> str:
    """Normalize Kurigram callback data to text."""
    if data is None:
        return ""
    if isinstance(data, bytes):
        return data.decode("utf-8", "replace")
    return data


def callback_text_of(q: CallbackQuery) -> str:
    """Return one callback query's data as text."""
    return callback_text(q.data)


def callback_args(q: CallbackQuery, count: int) -> list[str] | None:
    """Return the callback payload arguments, or ``None`` when malformed."""
    data = callback_text_of(q)
    if not data:
        return None
    segments = data.split(":")
    if len(segments) != count:
        return None
    return segments[1:]


def callback_args_optional(q: CallbackQuery, count: int) -> list[str] | None:
    """Return the callback payload arguments, allowing one extra segment."""
    data = callback_text_of(q)
    if not data:
        return None
    segments = data.split(":")
    if len(segments) not in (count, count + 1):
        return None
    return segments[1:]


def callback_numbers(q: CallbackQuery, count: int) -> list[int] | None:
    """Return the callback payload arguments parsed as integers."""
    args = callback_args(q, count)
    if args is None:
        return None
    try:
        return [int(arg) for arg in args]
    except ValueError:
        return None


async def cb_error_edit(
    q: CallbackQuery,
    text: str,
    *,
    log_label: str,
    parse_mode: Any = None,
    log_level: str = "warning",
) -> None:
    """Replace a callback message with a notice and catch edit failures."""
    _ = parse_mode
    await safe_edit_cb(
        q, text, log_level=log_level, log_label=log_label, catch_all=True
    )


async def send_log(bot: Client, text: str, **kwargs: Any) -> Message:
    """Post a federation log message to the configured logs destination."""
    chat_id, thread_id = cfg.logs
    return await send_rich(
        bot,
        chat_id,
        html_message(text),
        message_thread_id=thread_id,
        reply_markup=kwargs.get("reply_markup"),
    )


__all__ = [
    "ack_and_render",
    "answer_ack",
    "answer_alert",
    "answer_and_edit",
    "callback_args",
    "callback_args_optional",
    "callback_numbers",
    "callback_text",
    "callback_text_of",
    "cb_error_edit",
    "clear_markup",
    "clear_markup_cb",
    "edit_rich",
    "safe_edit",
    "safe_edit_cb",
    "safe_edit_message",
    "send_log",
]
