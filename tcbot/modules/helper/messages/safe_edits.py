# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Safe message delivery: channel posts, edits, and callback acknowledgements."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from telegram.error import BadRequest

from tcbot import cfg
from tcbot.utils.dispatch import throw_if_cancelled
from tcbot.utils.logger import get_logger

if TYPE_CHECKING:
    from collections.abc import Awaitable

    from telegram import Bot, CallbackQuery, InlineKeyboardMarkup, Message

log = get_logger(__name__)

# ─────────────────────────────── Safe edits ──────────────────────────────── #

_IGNORED = {"message is not modified", "message to edit not found", "chat not found"}


def _log_edit_failure(
    level: str, label: str | None, default_msg: str, exc: BaseException
) -> None:
    """Emit an edit-failure line at ``level`` using the call-site ``label``.

    With a label the message becomes ``"<label> edit failed: %s"`` so
    migrated inline sites keep byte-identical output; without one the
    helper's own default message is used. The exception is passed
    positionally, matching the inline ``log.debug("... edit failed: %s",
    exc)`` sites this consolidates.
    """
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
    """Run one edit coroutine with the shared benign-error policy.

    ``BadRequest`` values naming a harmless state (not modified, not found,
    chat gone) return silently; other ``BadRequest`` values log at
    ``log_level``. Generic ``Exception`` values either propagate or log at
    ``log_level`` depending on ``catch_all``. Cancellation always propagates.
    """
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
    parse_mode: str | None = "MarkdownV2",
    **kwargs: Any,
) -> None:
    """Edit a message via ``msg.edit_text``; swallow harmless not-modified errors.

    ``log_level`` selects the failure log level and ``log_label`` replaces
    the default message prefix, so migrated inline sites keep byte-identical
    output (``"<label> edit failed: %s"``). ``catch_all`` additionally
    swallows generic ``Exception`` failures at ``log_level`` instead of
    propagating them; cancellation always propagates. ``parse_mode``
    defaults to ``"MarkdownV2"``; pass ``None`` for plain text.
    """
    await _edit_via(
        msg.edit_text(text, parse_mode=parse_mode, **kwargs),
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
    parse_mode: str | None = "MarkdownV2",
    **kwargs: Any,
) -> None:
    """Edit a callback-query message; swallow harmless not-modified errors.

    Use this whenever a user can re-tap a button that lands them on the same
    content (e.g. a section sub-button while already viewing that section).
    The failure parameters behave exactly as in :func:`safe_edit`.
    """
    await _edit_via(
        q.edit_message_text(text, parse_mode=parse_mode, **kwargs),
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
    parse_mode: str | None = "MarkdownV2",
    **kwargs: Any,
) -> None:
    """Edit a message by chat/message ID via ``bot.edit_message_text``.

    Used for prompts whose chat and message IDs were stored in conversation
    state instead of a live ``Message``/``CallbackQuery`` handle. Failure
    parameters behave exactly as in :func:`safe_edit`.
    """
    await _edit_via(
        bot.edit_message_text(
            text,
            chat_id=chat_id,
            message_id=message_id,
            parse_mode=parse_mode,
            **kwargs,
        ),
        log_level=log_level,
        log_label=log_label,
        catch_all=catch_all,
        default_msg="message edit failed: %s",
    )


async def clear_markup_cb(q: CallbackQuery) -> None:
    """Remove the inline keyboard from a callback-query message.

    Editing message text without ``reply_markup`` keeps the old buttons
    (the parameter is omitted from the API call), so ending a flow with
    only an edit would leave dead buttons behind. Call this after the
    edit; "not modified" (already removed) is swallowed like
    :func:`safe_edit_cb`.
    """
    try:
        await q.edit_message_reply_markup(reply_markup=None)
    except BadRequest as e:
        if any(i in str(e).lower() for i in _IGNORED):
            return
        log.warning("clear markup failed: %s", e)


async def answer_and_edit(q: CallbackQuery, text: str, **kwargs: Any) -> None:
    """Answer a callback query and edit its message in parallel.

    ``q.answer()`` and the inline edit are independent; gathering them starts
    both at once. The edit goes through :func:`safe_edit_cb`, so benign
    not-modified errors are swallowed like the raw callback sites it replaces.
    Cancellation always propagates instead of reading as success.
    """
    results = await asyncio.gather(
        q.answer(),
        safe_edit_cb(q, text, **kwargs),
        return_exceptions=True,
    )
    throw_if_cancelled(results)


async def ack_and_render(
    q: CallbackQuery, data_coro: Awaitable[tuple[str, InlineKeyboardMarkup | None]]
) -> None:
    """Acknowledge the callback query and run the data coroutine in parallel, then edit.

    ``data_coro`` must be a coroutine that returns ``(text, kb)``. Gathering
    ``q.answer()`` with the DB fetch starts both simultaneously, cutting latency
    versus the old sequential pattern. On a data coroutine failure the query is
    answered but the message is left untouched. Cancellation always propagates.
    """
    ans, result = await asyncio.gather(q.answer(), data_coro, return_exceptions=True)
    throw_if_cancelled((ans, result))
    if isinstance(result, BaseException):
        log.error("ack_and_render data fetch failed: %s", result)
        return
    text, kb = result
    await safe_edit_cb(q, text, reply_markup=kb)


# ───────────────────────── Callback payload parsing ─────────────────────── #
# * Single owner for the "split the callback payload and read its numbers"
# * pattern. Every handler answered a malformed payload the same way, but
# * each one spelled the parse differently, so a stale button could reach a
# * handler that did not guard the shape.


async def send_log(bot: Bot, text: str, **kwargs: Any) -> Message:
    """Post a federation log message to the configured logs destination.

    Single owner for the log delivery contract: the destination comes from
    ``cfg.logs`` and the message always renders as MarkdownV2 inside the
    configured thread. Every federation executor posts its audit log
    through here, so a change to the contract lands in one place.
    """
    chat_id, thread_id = cfg.logs
    return await bot.send_message(
        chat_id,
        text,
        parse_mode="MarkdownV2",
        message_thread_id=thread_id,
        **kwargs,
    )


def callback_args(q: CallbackQuery, count: int) -> list[str] | None:
    """Return the callback payload arguments, or ``None`` when malformed.

    The payload must have exactly *count* colon-separated segments; the
    leading prefix is dropped and the remaining segments are returned in
    order. ``None`` when the payload is missing or has a different shape,
    so the caller can answer the button and stop instead of raising.
    """
    data = q.data
    if not data:
        return None
    segments = data.split(":")
    if len(segments) != count:
        return None
    return segments[1:]


def callback_args_optional(q: CallbackQuery, count: int) -> list[str] | None:
    """Return the callback payload arguments, allowing one extra segment.

    Some keyboards grew a trailing identifier: the prompt opener of a
    role picker, or the stable entity id of a paged record. The payload
    therefore has *count* segments, or *count + 1* when that identifier is
    present. Both shapes are accepted and the extra segment is returned as
    the last element, so the caller reads it when it is there.
    """
    data = q.data
    if not data:
        return None
    segments = data.split(":")
    if len(segments) not in (count, count + 1):
        return None
    return segments[1:]


def callback_numbers(q: CallbackQuery, count: int) -> list[int] | None:
    """Return the callback payload arguments parsed as integers.

    Same shape contract as :func:`callback_args`, and every argument must
    be an integer. ``None`` when the payload is missing, has a different
    shape, or holds a value that is not an integer.
    """
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
    parse_mode: str | None = "MarkdownV2",
    log_level: str = "debug",
) -> None:
    """Replace a callback message with a notice and drop its keyboard.

    Single owner for the refusal shape: the keyboard is removed so the
    button cannot be tapped again, the failure is logged at ``debug``
    because a refused callback is a normal outcome rather than a fault, and
    a generic error is swallowed so one broken edit never fails a handler.

    ``parse_mode`` follows the same convention as :func:`safe_edit_cb`:
    MarkdownV2 by default, and ``None`` for text produced with
    ``t(..., plain=True)``. The two must match, because a plain-text
    notice sent as MarkdownV2 fails to parse and a MarkdownV2 notice sent
    as plain text shows the escape backslashes to the user.

    Every callback handler that refuses a tap uses this, so the notice
    looks the same and the keyboard always disappears.
    """
    await safe_edit_cb(
        q,
        text,
        parse_mode=parse_mode,
        reply_markup=None,
        log_level=log_level,
        log_label=log_label,
        catch_all=True,
    )


async def safe_reply(
    msg: Message,
    text: str,
    *,
    log_label: str = "reply",
    parse_mode: str | None = "MarkdownV2",
    **kwargs: Any,
) -> None:
    """Send a reply via ``msg.reply_text``; log failures at debug.

    Replaces the recurring 3-line pattern of

        try:
            await msg.reply_text(...)
        except Exception as exc:
            log.debug("...reply failed: %s", exc)

    which is duplicated across the command modules and workflows. The
    ``log_label`` parameter is the human-readable name of the call site
    (e.g. ``"mute summary fallback"``); it appears in the debug log line
    so the operator can identify the source without grepping for the
    function name.

    ``parse_mode`` defaults to ``"MarkdownV2"`` for formatted replies; pass
    ``None`` for plain-text replies (error strings, constants, community
    names) so Telegram performs no entity parsing, exactly like a bare
    ``reply_text`` call without the parameter.

    Failures are logged at ``debug`` (not ``warning``) because a failed
    ``reply_text`` is almost always benign: the user blocked the bot,
    the chat was deleted, or the message thread was closed.
    """
    try:
        await msg.reply_text(text, parse_mode=parse_mode, **kwargs)
    except Exception as exc:
        log.debug("%s reply failed: %s", log_label, exc)
