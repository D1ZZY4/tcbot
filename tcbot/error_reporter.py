# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Centralized error reporter: classifies, formats, dedupes, ships to LOG_ERRORS."""

from __future__ import annotations

import asyncio
import contextlib
import platform
import re
import sys
import traceback
from typing import TYPE_CHECKING

import telegram.error as _te
from pymongo.errors import ConnectionFailure

from tcbot import cfg
from tcbot.utils import logger as logger_mod
from tcbot.utils.circuit_breaker import CircuitOpenError
from tcbot.utils.formatter import bold, code, esc, pre
from tcbot.utils.logger import get_logger
from tcbot.utils.time_and_date import monotonic, utc_now

if TYPE_CHECKING:
    import logging

    from telegram import Bot

log = get_logger("tcbot.error_reporter")

# * Log-noise patterns come from log_execution wrapping every handler.
_BENIGN_PATTERNS: tuple[str, ...] = (
    "message is not modified",
    "message to edit not found",
    "message to delete not found",
    "query is too old",
    "message is too old",
    "message can't be edited",
)
_LOG_NOISE_PATTERNS: tuple[str, ...] = (" raised after ",)
_OWNER_ONLY_TYPES: tuple[type[BaseException], ...] = (_te.Conflict, _te.InvalidToken)


def _benign(exc: BaseException | None) -> bool:
    """Check recoverable no-op (cancel, circuit, outage, known Telegram no-ops)."""
    if exc is None:
        return False
    if isinstance(exc, asyncio.CancelledError):
        return True
    if isinstance(exc, (ConnectionFailure, CircuitOpenError)):
        return True
    msg = str(exc).lower()
    return any(p in msg for p in _BENIGN_PATTERNS)


def _is_benign(exc: BaseException | None) -> bool:
    """Return True when the exception is a recoverable no-op.

    The reporter exists precisely for unexpected failures, so a predicate
    that itself fails must never discard the report: the unknown state is
    reported instead of swallowed.
    """
    if exc is None:
        return False
    try:
        return _benign(exc)
    except Exception as check_exc:
        log.warning("Benign check failed, treating as reportable: %s", check_exc)
        return False


def _log_noise(record: logging.LogRecord | None) -> bool:
    """Check record duplication an already-reported error."""
    return bool(record) and any(p in record.getMessage() for p in _LOG_NOISE_PATTERNS)


def _owner_only(exc: BaseException | None) -> bool:
    """Check owner-only routing to the owner DM only."""
    return exc is not None and isinstance(exc, _OWNER_ONLY_TYPES)


_ACTION_HINTS: tuple[tuple[str, str], ...] = (
    (
        "MongoDB Circuit Open",
        "MongoDB is unreachable; the circuit is open and calls fail fast "
        "until recovery. Check Atlas reachability, then retry.",
    ),
    ("[DB]", "Check MongoDB reachability and credentials, then retry the action."),
    ("Rate Limit", "Telegram asked to slow down; no action needed unless it persists."),
    ("Timed Out", "Transient Telegram hiccup; retry the action."),
    ("Polling Conflict", "Two bot instances are polling; stop the duplicate."),
    ("Invalid Token", "Token revoked or wrong; update BOT_TOKEN and restart."),
    ("Forbidden", "Bot lacks admin rights in the target chat; re-promote it."),
    ("Bad Request", "Check the reported call arguments for a bad ID or text."),
    ("Network", "Transient connectivity issue; retry the action."),
    ("Timeout", "Operation exceeded its deadline; retry the action."),
    ("Code Bug", "Needs a code fix; see the traceback below."),
    ("[?] Unknown", "No exception attached; check the message and location above."),
    ("Circuit Open", "Telegram circuit is open; retry after the cooldown."),
    (
        "MTProto Auth",
        "MTProto auth key is dead; stop every instance, delete the session "
        "docs from mtproto_state, then boot one.",
    ),
)


def _action_hint(label: str) -> str:
    """Return the operator action line for a classify label."""
    for marker, hint in _ACTION_HINTS:
        if marker in label:
            return hint
    return "Check the message and location above."


def _classify(exc: BaseException | None) -> str:
    """Return a human-readable label tag for the exception."""
    if exc is None:
        return "[?] Unknown"
    if isinstance(exc, _te.RetryAfter):
        return "[~] Rate Limit: Flood Wait"
    if isinstance(exc, _te.TimedOut):
        return "[~] Telegram Timed Out"
    if isinstance(exc, _te.Conflict):
        return "[~] Polling Conflict"
    if isinstance(exc, _te.BadRequest):
        return "[!] Telegram Bad Request"
    if isinstance(exc, _te.Forbidden):
        return "[!] Telegram Forbidden"
    if isinstance(exc, _te.InvalidToken):
        return "[!] Telegram Invalid Token"
    if isinstance(exc, _te.NetworkError):
        return "[~] Telegram Network Error"
    if isinstance(exc, _te.TelegramError):
        return "[!] Telegram API Error"
    mod = type(exc).__module__ or ""
    if "mongo" in mod:
        return "[DB] Database Error"
    if isinstance(exc, CircuitOpenError):
        return (
            "[~] MongoDB Circuit Open"
            if "mongodb" in str(exc).lower()
            else "[~] Circuit Open"
        )
    if "circuit_breaker" in mod:
        return "[~] Circuit Open"
    if isinstance(exc, asyncio.TimeoutError):
        return "[~] Async Timeout"
    if isinstance(exc, asyncio.CancelledError):
        return "[-] Task Cancelled"
    if isinstance(exc, (ConnectionError, TimeoutError, OSError)) or any(
        x in mod for x in ("httpx", "aiohttp", "urllib3", "ssl")
    ):
        return "[~] Network / Server Error"
    if type(exc).__name__ in ("AuthKeyDuplicated", "AuthKeyNotFound"):
        return "[~] MTProto Auth Key Invalidated"
    return "[!] Code Bug"


# * Set once during post-init via attach(); owner_id refreshable via set_owner().
_bot: Bot | None = None
_chat_id: int = 0
_thread_id: int | None = None
_owner_id: int = 0


def attach(bot: Bot, chat_id: int, thread_id: int | None, *, owner_id: int = 0) -> None:
    """Inject bot, log channel, and owner DM target; zero chat falls back to owner DM."""
    global _bot, _chat_id, _thread_id, _owner_id
    _bot = bot
    _owner_id = owner_id
    if chat_id == 0 and owner_id > 0:
        _chat_id = owner_id
        _thread_id = None
        log.warning("error_reporter.attach without chat_id; falling back to owner DM")
    else:
        _chat_id = chat_id
        _thread_id = thread_id
    if owner_id <= 0:
        log.warning(
            "error_reporter.attach with owner_id=%d; owner DM disabled",
            owner_id,
        )
    # * Register the shipping sink with the logger. The logger lives in the
    # * utils layer and must not import this module, so the dependency is
    # * inverted: this side registers, the logger calls.
    logger_mod.set_record_sink(_ship_record)


async def _ship_record(record: logging.LogRecord) -> None:
    """Ship a log record to the error channel.

    A wrapper, so the registered sink resolves ``report_record`` at call
    time: an override of the reporter then takes effect without a
    re-attach.
    """
    await report_record(record)


def set_owner(owner_id: int) -> None:
    """Update the owner-DM target after a runtime ownership transfer."""
    global _owner_id
    _owner_id = owner_id


_DEDUPE_WINDOW = 30.0
_RECENT_MAX: int = 1000
_recent: dict[tuple[object, ...], float] = {}
_OWNER_WINDOW: float = 3600.0
_OWNER_BUDGET: int = 3
_OWNER_MAX: int = 1000
_owner_sent: dict[tuple[object, ...], tuple[float, int]] = {}


def _owner_suppressed(fp: tuple[object, ...]) -> bool:
    """Check hourly owner budget its hourly owner budget."""
    now = monotonic()
    if len(_owner_sent) >= _OWNER_MAX:
        for key in [
            k for k, (at, _) in _owner_sent.items() if now - at >= _OWNER_WINDOW
        ]:
            del _owner_sent[key]
    start, count = _owner_sent.get(fp, (now, 0))
    if now - start >= _OWNER_WINDOW:
        start, count = now, 0
    if count >= _OWNER_BUDGET:
        _owner_sent[fp] = (start, count)
        return True
    _owner_sent[fp] = (start, count + 1)
    return False


_MAX_CONTEXT_LEN: int = 120
_TASK_ID_RE = re.compile(r"Task-\d+")
_HEX_ADDR_RE = re.compile(r"0x[0-9a-fA-F]+")


def _normalize_fp_text(text: str) -> str:
    """Stabilize volatile tokens so recurring failures dedupe."""
    return _HEX_ADDR_RE.sub("0x#", _TASK_ID_RE.sub("Task-#", text))


def _fingerprint_exc(exc: BaseException) -> tuple[object, ...]:
    """Build a coarse identity for an exception."""
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
    """Mark fp seen; True if already seen within the dedupe window."""
    now = monotonic()
    for key in [k for k, at in _recent.items() if now - at > _DEDUPE_WINDOW]:
        del _recent[key]
    if len(_recent) >= _RECENT_MAX:
        for key, _ in sorted(_recent.items(), key=lambda x: x[1])[: _RECENT_MAX // 10]:
            del _recent[key]
    if fp in _recent:
        return True
    _recent[fp] = now
    return False


def _dedup(exc: BaseException | None, record: logging.LogRecord | None) -> bool:
    """Check whether deduped within the window."""
    if exc is not None:
        return _seen_recently(_fingerprint_exc(exc))
    return _seen_recently(_fingerprint_record(record)) if record else False


# * Telegram caps at 4096 chars; budget keeps output safely under it.
_MAX_TB = 2200
_MAX_MSG = 250
_MAX_CTX = 250
_TB_FRAMES = 8
_MAX_LINE_CONTENT: int = 100
_REPORT_SEP_LEN: int = 30


def _shorten_path(path: str) -> str:
    """Convert a filesystem path to a compact project-relative form."""
    p = path.replace("\\", "/")
    if "tcbot/" in p:
        return "tcbot/" + p.split("tcbot/")[-1]
    if ".venv/Lib/site-packages/" in p:
        return p.split(".venv/Lib/site-packages/")[-1]
    if ".venv/lib/python" in p:
        return p.split("site-packages/")[-1]
    return p.rsplit("/", 1)[-1]


def _condensed_tb(exc: BaseException) -> str:
    """Build a compact ``file:line in func`` traceback with the last frames."""
    frames = traceback.extract_tb(exc.__traceback__)
    last = frames[-_TB_FRAMES:]
    lines: list[str] = []
    for f in last:
        lines.append(f"  {_shorten_path(f.filename or '?')}:{f.lineno} in {f.name}")
        if f.line:
            lines.append(f"      {f.line.strip()[:_MAX_LINE_CONTENT]}")
    lines.append(f"{type(exc).__name__}: {exc}")
    out = "\n".join(lines)
    return "...(trimmed)\n" + out[-_MAX_TB:] if len(out) > _MAX_TB else out


def _location(
    exc: BaseException | None, record: logging.LogRecord | None
) -> tuple[str, str, int]:
    """Return (file, func, line) for the report header."""
    if record is not None:
        return _shorten_path(record.pathname), record.funcName, record.lineno
    if exc is not None and exc.__traceback__ is not None:
        frames = traceback.extract_tb(exc.__traceback__)
        if frames:
            last = frames[-1]
            return _shorten_path(last.filename or "?"), last.name, last.lineno or 0
    return "?", "?", 0


_TOKEN_RE = re.compile(r"\b\d{6,}:[A-Za-z0-9_-]{20,}\b")
_MONGO_AUTH_RE = re.compile(r"://(?:[^:@/\s]+)?:[^@/\s]+@")


def _scrub_secrets(text: str) -> str:
    """Redact exact configured values first, then credential-shaped patterns."""
    for secret in (
        cfg.bot_token,
        cfg.mongodb_uri,
        cfg.api_hash,
        cfg.webhook_secret,
        cfg.cron_secret,
        cfg.redis_url,
    ):
        if secret and secret in text:
            text = text.replace(secret, "[REDACTED]")
    text = _TOKEN_RE.sub("[REDACTED_TOKEN]", text)
    return _MONGO_AUTH_RE.sub("://[REDACTED]@", text)


def scrub_text(text: str) -> str:
    """Public wrapper for secret redaction of console-bound strings."""
    return _scrub_secrets(text)


def build_error_message(
    *,
    exc: BaseException | None = None,
    record: logging.LogRecord | None = None,
    context: str | None = None,
) -> str:
    """Build a MarkdownV2-formatted error message for Telegram."""
    now = utc_now()
    time_str = now.strftime("%H:%M:%S UTC")
    date_str = now.strftime("%d-%m-%Y")
    if record and record.exc_info and record.exc_info[1]:
        exc = exc or record.exc_info[1]
    raw_msg = record.getMessage() if record else str(exc) if exc else "No detail."
    raw_msg = _scrub_secrets(raw_msg)
    file_part, func_name, line_no = _location(exc, record)
    label = _classify(exc)
    action = _action_hint(label)
    tb_block = ""
    if exc and exc.__traceback__:
        tb_block = (
            f"\n\n{bold('Traceback:')}\n{pre(_scrub_secrets(_condensed_tb(exc)))}"
        )
    ctx_block = ""
    if context:
        ctx_block = (
            f"\n\n{bold('Context:')}\n{code(_scrub_secrets(str(context))[:_MAX_CTX])}"
        )
    py_ver = sys.version.split()[0]
    host = platform.node() or "?"
    sep = "\\-" * _REPORT_SEP_LEN
    return (
        f"{bold('Error Report')}\n"
        f"{sep}\n"
        f"{bold('Type:')} {esc(label)}\n"
        f"{bold('Action:')} {esc(action)}\n"
        f"{bold('Where:')} {code(f'{file_part}:{line_no}')} in {code(func_name)}\n"
        f"{bold('When:')} {esc(time_str)} \\- {esc(date_str)}\n"
        f"{bold('Host:')} Python {esc(py_ver)} @ {esc(host)}\n"
        f"{sep}\n"
        f"{bold('Message:')}\n{code(raw_msg[:_MAX_MSG])}"
        f"{tb_block}"
        f"{ctx_block}"
    )


# * At most _SEND_BUDGET per window; overflow counts into one summary.
_SEND_BUDGET: int = 20
_SEND_WINDOW: float = 60.0
_send_window_start: float = 0.0
_sent_in_window: int = 0
_suppressed_in_window: int = 0


async def _ship_throttled(text: str) -> None:
    """Send to LOG_ERRORS within budget, else count for the summary."""
    global _send_window_start, _sent_in_window, _suppressed_in_window
    if not _bot or not _chat_id:
        return
    now = monotonic()
    if now - _send_window_start >= _SEND_WINDOW:
        _send_window_start = now
        _sent_in_window = 0
        if _suppressed_in_window:
            suppressed = _suppressed_in_window
            _suppressed_in_window = 0
            try:
                await _bot.send_message(
                    _chat_id,
                    f"Error reporter: {suppressed} further error\\(s\\) "
                    f"suppressed in the last {_SEND_WINDOW:.0f}s window\\.",
                    parse_mode="MarkdownV2",
                    message_thread_id=_thread_id,
                )
            except Exception as exc:
                log.warning("Failed to ship error summary to LOG_ERRORS: %s", exc)
                return
    if _sent_in_window >= _SEND_BUDGET:
        _suppressed_in_window += 1
        return
    _sent_in_window += 1
    try:
        await _bot.send_message(
            _chat_id, text, parse_mode="MarkdownV2", message_thread_id=_thread_id
        )
    except Exception as exc:
        log.warning("Failed to ship error to LOG_ERRORS: %s", exc)


async def send_to_log_errors(text: str) -> None:
    """Fire-and-forget send to LOG_ERRORS (throttled)."""
    if not _bot or not _chat_id:
        return
    await _ship_throttled(text)


async def send_to_owner(text: str) -> None:
    """Fire-and-forget DM to the owner for infra-only errors."""
    if not _bot or not _owner_id:
        return
    try:
        await _bot.send_message(_owner_id, text, parse_mode="MarkdownV2")
    except Exception as exc:
        log.warning("Failed to send owner DM: %s", exc)


async def report_exc(exc: BaseException, context: str | None = None) -> None:
    """Report an exception; owner-only errors go to owner DM."""
    if _is_benign(exc) or _dedup(exc, None):
        return
    text = build_error_message(exc=exc, context=context)
    if _owner_only(exc):
        if _owner_suppressed(_fingerprint_exc(exc)):
            log.debug("Owner DM suppressed: budget spent.")
            return
        await send_to_owner(text)
    else:
        await send_to_log_errors(text)


async def report_record(record: logging.LogRecord) -> None:
    """Report a LogRecord; deduped and noise-filtered."""
    exc = record.exc_info[1] if record.exc_info else None
    if _is_benign(exc) or _log_noise(record) or _dedup(exc, record):
        return
    text = build_error_message(record=record)
    if _owner_only(exc):
        fp = _fingerprint_exc(exc) if exc is not None else _fingerprint_record(record)
        if _owner_suppressed(fp):
            log.debug("Owner DM suppressed: budget spent.")
            return
        await send_to_owner(text)
    else:
        await send_to_log_errors(text)
