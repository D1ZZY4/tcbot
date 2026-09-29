# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Reporter state: attach, owner routing, dedupe windows, and fingerprints."""

from __future__ import annotations

import contextlib
import re
from typing import TYPE_CHECKING

from tcbot.utils.logger import get_logger
from tcbot.utils.time_and_date import monotonic

if TYPE_CHECKING:
    import logging

    from telegram import Bot

# * Fixed logger name (not __name__): records must land on the documented
# * "tcbot.utils.error_reporter" channel after the split.
log = get_logger("tcbot.utils.error_reporter")

# * Set once during bot post-init via attach(); owner_id is refreshable
# * via set_owner() so that ownership-transfer DMs route to the new owner.
_bot: Bot | None = None
_chat_id: int = 0
_thread_id: int | None = None
_owner_id: int = 0


def attach(
    bot: Bot,
    chat_id: int,
    thread_id: int | None,
    *,
    owner_id: int = 0,
) -> None:
    """Inject live bot instance, log channel config, and owner DM target.

    Validates the inputs at attach-time so a misconfiguration is logged
    at startup rather than producing silent no-ops at error-report time.
    A zero ``chat_id`` is accepted (the bot may legitimately be deployed
    without a log channel) but is logged at WARNING so the operator
    notices on first boot. Negative IDs are normal group/channel IDs and
    need no warning.
    """
    global _bot, _chat_id, _thread_id, _owner_id
    _bot = bot
    _chat_id = chat_id
    _thread_id = thread_id
    _owner_id = owner_id
    if chat_id == 0:
        log.warning(
            "error_reporter.attach called without a chat_id; LOG_ERRORS "
            "shipping is disabled until one is configured",
        )
    if owner_id <= 0:
        log.warning(
            "error_reporter.attach called with owner_id=%d; owner-DM "
            "shipping of infra errors is disabled until a positive owner_id "
            "is configured (typically after OWNER_ID env var is read)",
            owner_id,
        )


def set_owner(owner_id: int) -> None:
    """Update the owner-DM target after a runtime ownership transfer.

    Called from ``cmd_transfer`` after the new founder is set, so that the
    next infra error DM goes to the new owner instead of the old one.
    """
    global _owner_id
    _owner_id = owner_id


# * Same exception object travels through log_execution + PTB error handler;
# * a fingerprinted TTL set keeps the channel to ONE report per incident.
_DEDUPE_WINDOW = 30.0
_RECENT_MAX: int = 1000
_recent: dict[tuple[object, ...], float] = {}

# * Owner-only errors (a duplicate instance's Conflict storm, a revoked
# * token) repeat identically forever; the 30 s dedupe above only spaces
# * them to one DM per 30 s with no backstop. Past a small hourly budget
# * per fingerprint the owner already knows, so suppress further repeats.
_OWNER_WINDOW: float = 3600.0
_OWNER_BUDGET: int = 3
_OWNER_MAX: int = 1000
_owner_sent: dict[tuple[object, ...], tuple[float, int]] = {}


def _owner_suppressed(fp: tuple[object, ...]) -> bool:
    """Return True when this owner fingerprint exhausted its hourly budget."""
    now = monotonic()
    if len(_owner_sent) >= _OWNER_MAX:
        expired = [
            key
            for key, (sent_at, _) in _owner_sent.items()
            if now - sent_at >= _OWNER_WINDOW
        ]
        for key in expired:
            del _owner_sent[key]
    start, count = _owner_sent.get(fp, (now, 0))
    if now - start >= _OWNER_WINDOW:
        start, count = now, 0
    if count >= _OWNER_BUDGET:
        _owner_sent[fp] = (start, count)
        return True
    _owner_sent[fp] = (start, count + 1)
    return False


# * Maximum characters captured from an exception or log message in a fingerprint.
_MAX_CONTEXT_LEN: int = 120

_TASK_ID_RE = re.compile(r"Task-\d+")
_HEX_ADDR_RE = re.compile(r"0x[0-9a-fA-F]+")


def _normalize_fp_text(text: str) -> str:
    """Stabilize volatile tokens so recurring background failures dedupe.

    Asyncio task names (Task-NNNN) and object addresses differ per crash
    while the underlying fault repeats; without this each repeat mints a
    fresh fingerprint and the channel floods (seen live with a crashing
    Pyrogram handle_updates loop shipping dozens of cards).
    """
    text = _TASK_ID_RE.sub("Task-#", text)
    return _HEX_ADDR_RE.sub("0x#", text)


def _fingerprint_exc(exc: BaseException) -> tuple[object, ...]:
    """Build a coarse identity for an exception that survives class+location+message."""
    tb = exc.__traceback__
    last = None
    while tb is not None:
        last = tb
        tb = tb.tb_next
    line = last.tb_lineno if last else 0
    file_part = ""
    if last is not None:
        with contextlib.suppress(AttributeError):
            file_part = last.tb_frame.f_code.co_filename
    return (
        "exc",
        type(exc).__name__,
        file_part,
        line,
        _normalize_fp_text(str(exc))[:_MAX_CONTEXT_LEN],
    )


def _fingerprint_record(record: logging.LogRecord) -> tuple[object, ...]:
    """Build a coarse identity for a log record."""
    return (
        "log",
        record.name,
        record.lineno,
        _normalize_fp_text(record.getMessage())[:_MAX_CONTEXT_LEN],
    )


def _seen_recently(fp: tuple[object, ...]) -> bool:
    """Mark fp as seen now; return True if it was already seen within the window."""
    now = monotonic()
    expired = [
        key for key, seen_at in _recent.items() if now - seen_at > _DEDUPE_WINDOW
    ]
    for key in expired:
        del _recent[key]
    if len(_recent) >= _RECENT_MAX:
        # * Evict the oldest 10% when the cap is hit to avoid unbounded memory growth
        # * during storm scenarios with many distinct error fingerprints.
        for key, _ in sorted(_recent.items(), key=lambda x: x[1])[: _RECENT_MAX // 10]:
            del _recent[key]
    if fp in _recent:
        return True
    _recent[fp] = now
    return False


def _dedup(exc: BaseException | None, record: logging.LogRecord | None) -> bool:
    """Return True if (exc, record) has been reported within the dedupe window.

    Accepts both shapes so callers don't have to re-implement the
    fingerprint selection. When both are present (typical for
    ``log.exception()`` which produces a record with embedded exc_info)
    the exception fingerprint is preferred because it carries more
    identifying context.
    """
    if exc is not None:
        return _seen_recently(_fingerprint_exc(exc))
    if record is not None:
        return _seen_recently(_fingerprint_record(record))
    return False
