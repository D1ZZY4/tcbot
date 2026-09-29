# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Report shipping: throttled channel sends, owner DMs, and report entry points."""

from __future__ import annotations

import logging

from tcbot.utils.time_and_date import monotonic

from . import state as _state
from .classify import _benign, _log_noise, _owner_only
from .format import build_error_message
from .state import (
    _dedup,
    _fingerprint_exc,
    _fingerprint_record,
    _owner_suppressed,
)

# * Shipping is throttled: at most _SEND_BUDGET reports per window go to
# * LOG_ERRORS. Overflow is counted, and a single summary is sent when the
# * next window opens. Without this, escalating more paths to error-level
# * would risk Telegram FloodWait during incident storms.
_SEND_BUDGET: int = 20
_SEND_WINDOW: float = 60.0
_send_window_start: float = 0.0
_sent_in_window: int = 0
_suppressed_in_window: int = 0


async def _ship_throttled(text: str) -> None:
    """Send to LOG_ERRORS within budget, else count for the summary."""
    global _send_window_start, _sent_in_window, _suppressed_in_window
    if not _state._bot or not _state._chat_id:
        return
    now = monotonic()
    if now - _send_window_start >= _SEND_WINDOW:
        _send_window_start = now
        _sent_in_window = 0
        if _suppressed_in_window:
            suppressed = _suppressed_in_window
            _suppressed_in_window = 0
            try:
                await _state._bot.send_message(
                    _state._chat_id,
                    f"Error reporter: {suppressed} further error\\(s\\) "
                    f"suppressed in the last {_SEND_WINDOW:.0f}s window\\.",
                    parse_mode="MarkdownV2",
                    message_thread_id=_state._thread_id,
                )
            except Exception as exc:
                logging.getLogger().warning(
                    "Failed to ship error summary to LOG_ERRORS: %s", exc
                )
                return
    if _sent_in_window >= _SEND_BUDGET:
        _suppressed_in_window += 1
        return
    _sent_in_window += 1
    try:
        await _state._bot.send_message(
            _state._chat_id,
            text,
            parse_mode="MarkdownV2",
            message_thread_id=_state._thread_id,
        )
    except Exception as exc:
        # * Log via the root logger at WARNING, not through the dedicated
        # * error_reporter logger (which is in the _SUPPRESS_PREFIXES list
        # * in logger.py to prevent recursion). Falling back to the root
        # * logger ensures the failure surfaces in console output even if
        # * the Telegram error handler is misconfigured.
        logging.getLogger().warning(
            "Failed to ship error to Telegram LOG_ERRORS: %s", exc
        )


async def send_to_log_errors(text: str) -> None:
    """Fire-and-forget send to LOG_ERRORS channel (throttled, see above)."""
    if not _state._bot or not _state._chat_id:
        return
    await _ship_throttled(text)


async def send_to_owner(text: str) -> None:
    """Fire-and-forget DM to the bot owner; used for infra/operator-only errors."""
    if not _state._bot or not _state._owner_id:
        return
    try:
        await _state._bot.send_message(
            _state._owner_id,
            text,
            parse_mode="MarkdownV2",
        )
    except Exception as exc:
        logging.getLogger().warning("Failed to send owner DM for infra error: %s", exc)


async def report_exc(
    exc: BaseException,
    context: str | None = None,
) -> None:
    """Report an exception; owner-only errors go to owner DM, others to log channel."""
    if _benign(exc):
        return
    if _dedup(exc, None):
        return
    text = build_error_message(exc=exc, context=context)
    if _owner_only(exc):
        if _owner_suppressed(_fingerprint_exc(exc)):
            logging.getLogger().debug("Owner DM suppressed: hourly budget spent.")
            return
        await send_to_owner(text)
    else:
        await send_to_log_errors(text)


async def report_record(record: logging.LogRecord) -> None:
    """Report a logging.LogRecord (from log.error() / log.critical()); deduped and noise-filtered."""
    exc = record.exc_info[1] if record.exc_info else None
    if _benign(exc):
        return
    if _log_noise(record):
        # * log_execution emits a per-handler summary that the PTB error handler
        # * follows up with a richer report; skip the noisier first one.
        return
    if _dedup(exc, record):
        return
    text = build_error_message(record=record)
    if _owner_only(exc):
        fp = _fingerprint_exc(exc) if exc is not None else _fingerprint_record(record)
        if _owner_suppressed(fp):
            logging.getLogger().debug("Owner DM suppressed: hourly budget spent.")
            return
        await send_to_owner(text)
    else:
        await send_to_log_errors(text)
