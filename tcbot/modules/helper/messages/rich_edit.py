# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Rich message editing: ``edit_rich`` and the safe edit helpers.

Sending and replying live in ``rich_msg.py``. The safe helpers edit through
the rich transport when the bot is a real PTB ``Bot`` and fall back to the
plain PTB edit for test doubles or non-PTB bots. ``send_log`` lives here
because its log payload is shared with the edit helpers. Callback answers and
keyboard-only edits have no rich equivalent and remain direct PTB calls.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from telegram import Bot
from telegram.error import BadRequest

from tcbot import cfg
from tcbot.modules.helper.messages.rich_link import _markup_dict
from tcbot.modules.helper.messages.rich_msg import (
    _message_with_buttons,
    html_message,
    send_rich,
)
from tcbot.utils.dispatch import throw_if_cancelled
from tcbot.utils.logger import get_logger

if TYPE_CHECKING:
    from collections.abc import Awaitable

    from telegram import CallbackQuery, InlineKeyboardMarkup, Message

log = get_logger(__name__)


# ───────────────────────────── edit_rich ──────────────────────────────── #


async def edit_rich(
    bot: Bot,
    chat_id: int | str,
    message_id: int,
    message: dict[str, Any],
    *,
    reply_markup: Any | None = None,
) -> Message:
    """Edit a message's rich content.

    PTB exposes ``editMessageText`` natively, so the rich payload is passed
    through ``api_kwargs`` instead of the generic ``do_api_request`` escape
    hatch. ``text`` is required by PTB's signature but omitted from the
    request: the Bot API requires *rich_message* when *text* is absent.
    """
    if not hasattr(bot, "edit_message_text"):
        raise RuntimeError("rich edit needs a Bot with edit_message_text support")

    payload, embedded = _message_with_buttons(message, reply_markup)
    api_kwargs: dict[str, Any] = {"rich_message": payload, "text": None}
    markup = _markup_dict(reply_markup)
    if markup is not None and not embedded:
        api_kwargs["reply_markup"] = markup
    return await bot.edit_message_text(
        text=None,  # type: ignore[arg-type]
        chat_id=chat_id,
        message_id=message_id,
        api_kwargs=api_kwargs,
    )


# ─────────────────────────────── Safe edits ─────────────────────────────── #

_IGNORED = {"message is not modified", "message to edit not found", "chat not found"}


def _rich_payload(text: str) -> dict[str, Any]:
    """Build the rich payload for any text, including plain notices."""
    return html_message(text)


def _bot_of(obj: object) -> Bot | None:
    """Return the bot of a PTB object, or None for lightweight fakes."""
    getter = getattr(obj, "get_bot", None)
    if getter is None:
        return None
    try:
        return getter()
    except Exception:
        return None


def _rich_ready(bot: object | None) -> bool:
    """Only a real PTB Bot can reach the Bot API rich-message methods."""
    return isinstance(bot, Bot)


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
) -> None:
    """Run one edit coroutine with the shared benign-error policy."""
    try:
        await do_edit
    except BadRequest as e:
        if any(i in str(e).lower() for i in _IGNORED):
            return
        _log_edit_failure(log_level, log_label, default_msg, e)
    except Exception as exc:
        if not catch_all:
            raise
        _log_edit_failure(log_level, log_label, default_msg, exc)


async def safe_edit(
    msg: Message,
    text: str,
    *,
    log_level: str = "warning",
    log_label: str | None = None,
    catch_all: bool = False,
    parse_mode: Any = None,
    **kwargs: Any,
) -> None:
    """Edit a message as a rich message; swallow harmless not-modified errors."""
    _ = parse_mode
    rich_bot = _bot_of(msg)
    if not isinstance(rich_bot, Bot):
        await _edit_via(
            msg.edit_text(text, **kwargs),
            log_level=log_level,
            log_label=log_label,
            catch_all=catch_all,
            default_msg="edit failed: %s",
        )
        return
    await _edit_via(
        edit_rich(
            rich_bot,
            msg.chat.id,
            msg.message_id,
            _rich_payload(text),
            reply_markup=kwargs.get("reply_markup"),
        ),
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
    parse_mode: Any = None,
    **kwargs: Any,
) -> None:
    """Edit a callback-query message as a rich message."""
    _ = parse_mode
    target = getattr(q, "message", None)
    rich_bot = _bot_of(q)
    if target is None or not isinstance(rich_bot, Bot):
        await _edit_via(
            q.edit_message_text(text, **kwargs),
            log_level=log_level,
            log_label=log_label,
            catch_all=catch_all,
            default_msg="callback edit failed: %s",
        )
        return
    await _edit_via(
        edit_rich(
            rich_bot,
            target.chat.id,
            target.message_id,
            _rich_payload(text),
            reply_markup=kwargs.get("reply_markup"),
        ),
        log_level=log_level,
        log_label=log_label,
        catch_all=catch_all,
        default_msg="callback edit failed: %s",
    )


async def safe_edit_message(
    bot: Bot,
    chat_id: int | None,
    message_id: int | None,
    text: str,
    *,
    log_level: str = "warning",
    log_label: str | None = None,
    catch_all: bool = False,
    parse_mode: Any = None,
    **kwargs: Any,
) -> None:
    """Edit a message by chat/message ID as a rich message."""
    _ = parse_mode
    if chat_id is None or message_id is None or not _rich_ready(bot):
        await _edit_via(
            bot.edit_message_text(
                text, chat_id=chat_id, message_id=message_id, **kwargs
            ),
            log_level=log_level,
            log_label=log_label,
            catch_all=catch_all,
            default_msg="message edit failed: %s",
        )
        return
    await _edit_via(
        edit_rich(
            bot,
            chat_id,
            message_id,
            _rich_payload(text),
            reply_markup=kwargs.get("reply_markup"),
        ),
        log_level=log_level,
        log_label=log_label,
        catch_all=catch_all,
        default_msg="message edit failed: %s",
    )


async def clear_markup_cb(q: CallbackQuery) -> None:
    """Remove the inline keyboard from a callback-query message."""
    try:
        await q.edit_message_reply_markup(reply_markup=None)
    except BadRequest as e:
        if any(i in str(e).lower() for i in _IGNORED):
            return
        log.warning("clear markup failed: %s", e)


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
        q.answer(),
        safe_edit_cb(q, text, **kwargs),
        return_exceptions=True,
    )
    throw_if_cancelled((answer_r, edit_r))
    if isinstance(answer_r, BaseException):
        log.debug("answer_and_edit answer failed: %s", answer_r)
    if isinstance(edit_r, BaseException):
        log.warning("answer_and_edit edit failed: %s", edit_r)


async def ack_and_render(
    q: CallbackQuery, data_coro: Awaitable[tuple[str, InlineKeyboardMarkup | None]]
) -> None:
    """Acknowledge the callback query and run the data coroutine in parallel."""
    ans, result = await asyncio.gather(q.answer(), data_coro, return_exceptions=True)
    throw_if_cancelled((ans, result))
    if isinstance(result, BaseException):
        log.error("ack_and_render data fetch failed: %s", result)
        return
    text, btn = result
    await safe_edit_cb(q, text, reply_markup=btn)


def callback_args(q: CallbackQuery, count: int) -> list[str] | None:
    """Return the callback payload arguments, or ``None`` when malformed."""
    data = q.data
    if not data:
        return None
    segments = data.split(":")
    if len(segments) != count:
        return None
    return segments[1:]


def callback_args_optional(q: CallbackQuery, count: int) -> list[str] | None:
    """Return the callback payload arguments, allowing one extra segment."""
    data = q.data
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
    """Replace a callback message with a notice and drop its keyboard."""
    await safe_edit_cb(
        q,
        text,
        parse_mode=parse_mode,
        reply_markup=None,
        log_level=log_level,
        log_label=log_label,
        catch_all=True,
    )


async def send_log(bot: Bot, text: str, **kwargs: Any) -> Message:
    """Post a federation log message to the configured logs destination."""
    chat_id, thread_id = cfg.logs
    if not _rich_ready(bot):
        return await bot.send_message(
            chat_id,
            text,
            message_thread_id=thread_id,
            reply_markup=kwargs.get("reply_markup"),
        )
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
    "cb_error_edit",
    "clear_markup_cb",
    "edit_rich",
    "safe_edit",
    "safe_edit_cb",
    "safe_edit_message",
    "send_log",
]
