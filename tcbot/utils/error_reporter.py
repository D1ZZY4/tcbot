# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Studio

"""Centralized error reporter: classifies, formats, dedupes, and ships errors to LOG_ERRORS."""

from __future__ import annotations

import asyncio
import logging
import platform
import sys
import time
import traceback
from typing import TYPE_CHECKING

import telegram.error as _te

from tcbot.utils.timedate_format import utc_now

if TYPE_CHECKING:
    from telegram import Bot

log = logging.getLogger(__name__)


# ─────────────────────── Module-Level State ─────────────────────── #
# * Set once during bot post-init via attach(); never mutated after that

_bot: "Bot | None" = None
_chat_id: int = 0
_thread_id: int | None = None


def attach(bot: "Bot", chat_id: int, thread_id: int | None) -> None:
    """Inject live bot instance and log channel config."""
    global _bot, _chat_id, _thread_id
    _bot = bot
    _chat_id = chat_id
    _thread_id = thread_id


# ────────────── Filter benign + noisy log records ───────────────── #
# * Benign errors are caught/recovered by safe_edit; we never ship them.
# * Log-noise patterns come from log_execution wrapping every handler.

_BENIGN_PATTERNS: tuple[str, ...] = (
    "message is not modified",
    "message to edit not found",
    "message to delete not found",
    "query is too old",
    "message is too old",
    "message can't be edited",
)

_LOG_NOISE_PATTERNS: tuple[str, ...] = (
    " raised after ",  # log_execution's per-handler exception summary
)


def _benign(exc: BaseException | None) -> bool:
    """Return True when the exception is a recoverable, well-known no-op."""
    if exc is None:
        return False
    msg = str(exc).lower()
    return any(p in msg for p in _BENIGN_PATTERNS)


def _log_noise(record: logging.LogRecord | None) -> bool:
    """Return True when the log record duplicates info already reported elsewhere."""
    if record is None:
        return False
    msg = record.getMessage()
    return any(p in msg for p in _LOG_NOISE_PATTERNS)


# ─────────────────── Dedupe within a short window ────────────────── #
# * Same exception object travels through log_execution + PTB error handler;
# * a fingerprinted TTL set keeps the channel to ONE report per incident.

_DEDUPE_WINDOW = 30.0
_recent: dict[tuple, float] = {}


def _fingerprint(
    exc: BaseException | None,
    record: logging.LogRecord | None,
) -> tuple:
    """Build a coarse identity that matches across log_execution + PTB handler paths."""
    if exc is not None:
        tb = exc.__traceback__
        last = None
        while tb is not None:
            last = tb
            tb = tb.tb_next
        line = last.tb_lineno if last else 0
        file_part = ""
        if last is not None:
            try:
                file_part = last.tb_frame.f_code.co_filename
            except AttributeError:
                pass
        return (type(exc).__name__, file_part, line, str(exc)[:120])
    if record is not None:
        return ("log", record.name, record.lineno, record.getMessage()[:120])
    return ("?",)


def _seen_recently(fp: tuple) -> bool:
    """Mark fp as seen now; return True if it was already seen within the window."""
    now = time.monotonic()
    for k in list(_recent):
        if now - _recent[k] > _DEDUPE_WINDOW:
            del _recent[k]
    if fp in _recent:
        return True
    _recent[fp] = now
    return False


# ────────────────────── Error Classification ────────────────────── #


def _classify(exc: BaseException | None) -> str:
    """Return a human-readable label tag for the exception."""
    if exc is None:
        return "[?] Unknown"

    # * Specific Telegram error subclasses first; BadRequest inherits NetworkError.
    if isinstance(exc, _te.RetryAfter):
        return "[~] Rate Limit: Flood Wait"
    if isinstance(exc, _te.TimedOut):
        return "[~] Telegram Timed Out"
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
    if any(x in mod for x in ("motor", "pymongo", "mongo")):
        return "[DB] Database Error"

    if isinstance(exc, asyncio.TimeoutError):
        return "[~] Async Timeout"
    if isinstance(exc, asyncio.CancelledError):
        return "[-] Task Cancelled"

    if isinstance(exc, (ConnectionError, TimeoutError, OSError)) or any(
        x in mod for x in ("httpx", "aiohttp", "urllib3", "ssl")
    ):
        return "[~] Network / Server Error"

    return "[!] Code Bug"


# ─────────────────────── Message Formatting ─────────────────────── #
# * Telegram hard-caps a message at 4096 chars (incl. HTML). Budget below
# * keeps the rendered output safely under that limit even with HTML tags.

_MAX_TB = 2200
_MAX_MSG = 250
_MAX_CTX = 250
_TB_FRAMES = 8


def _esc(s: str | None) -> str:
    """Escape HTML special characters for Telegram HTML parse mode."""
    if s is None:
        return ""
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _shorten_path(path: str) -> str:
    """Convert raw filesystem path to a compact project-relative form."""
    p = path.replace("\\", "/")
    if "tcbot/" in p:
        return "tcbot/" + p.split("tcbot/")[-1]
    if ".venv/Lib/site-packages/" in p:
        return p.split(".venv/Lib/site-packages/")[-1]
    if ".venv/lib/python" in p:
        # *nix venv
        return p.split("site-packages/")[-1]
    return p.rsplit("/", 1)[-1]


def _condensed_tb(exc: BaseException) -> str:
    """Build a compact `file:line in func` traceback with the last few frames."""
    frames = traceback.extract_tb(exc.__traceback__)
    last = frames[-_TB_FRAMES:]
    lines: list[str] = []
    for f in last:
        path = _shorten_path(f.filename or "?")
        lines.append(f"  {path}:{f.lineno} in {f.name}")
        if f.line:
            lines.append(f"      {f.line.strip()[:100]}")
    lines.append(f"{type(exc).__name__}: {exc}")
    out = "\n".join(lines)
    if len(out) > _MAX_TB:
        out = "…(trimmed)\n" + out[-_MAX_TB:]
    return out


def _location(
    exc: BaseException | None,
    record: logging.LogRecord | None,
) -> tuple[str, str, int]:
    """Return (file, func, line) for the report header."""
    if record is not None:
        path = _shorten_path(record.pathname)
        return path, record.funcName, record.lineno
    if exc is not None and exc.__traceback__ is not None:
        frames = traceback.extract_tb(exc.__traceback__)
        if frames:
            last = frames[-1]
            return _shorten_path(last.filename or "?"), last.name, last.lineno
    return "?", "?", 0


def build_error_message(
    *,
    exc: BaseException | None = None,
    record: logging.LogRecord | None = None,
    context: str | None = None,
) -> str:
    """Build a complete HTML-formatted error message for Telegram."""
    now = utc_now()
    time_str = now.strftime("%H:%M:%S UTC")
    date_str = now.strftime("%d-%m-%Y")

    if record and record.exc_info and record.exc_info[1]:
        exc = exc or record.exc_info[1]

    if record:
        raw_msg = record.getMessage()
    elif exc:
        raw_msg = str(exc)
    else:
        raw_msg = "No detail available."

    file_part, func_name, line_no = _location(exc, record)
    label = _classify(exc)

    tb_block = ""
    if exc and exc.__traceback__:
        tb_block = f"\n\n<b>Traceback:</b>\n<pre>{_esc(_condensed_tb(exc))}</pre>"

    ctx_block = ""
    if context:
        ctx_block = f"\n\n<b>Context:</b>\n<code>{_esc(str(context)[:_MAX_CTX])}</code>"

    py_ver = sys.version.split()[0]
    host = platform.node() or "?"
    sep = "━" * 30

    return (
        f"<b>Error Report</b>\n"
        f"{sep}\n"
        f"<b>Type:</b> {label}\n"
        f"<b>Where:</b> <code>{_esc(file_part)}:{line_no}</code> in <code>{_esc(func_name)}</code>\n"
        f"<b>When:</b> {time_str} · {date_str}\n"
        f"<b>Host:</b> Python {py_ver} @ {_esc(host)}\n"
        f"{sep}\n"
        f"<b>Message:</b>\n<code>{_esc(raw_msg[:_MAX_MSG])}</code>"
        f"{tb_block}"
        f"{ctx_block}"
    )


# ───────────────────────── Low-Level Send ───────────────────────── #


async def send_to_log_errors(text: str) -> None:
    """Fire-and-forget send to LOG_ERRORS channel."""
    if not _bot or not _chat_id:
        return
    try:
        await _bot.send_message(
            _chat_id,
            text,
            parse_mode="HTML",
            message_thread_id=_thread_id,
        )
    except Exception as exc:
        # * Use a quiet logger name so the failure is not re-shipped.
        logging.getLogger("tcbot.utils.error_reporter").warning(
            "Failed to ship error to Telegram: %s", exc
        )


# ────────────────────── Convenience Wrappers ────────────────────── #


async def report_exc(
    exc: BaseException,
    context: str | None = None,
) -> None:
    """Report an exception with optional context string; benign / duplicate reports are skipped."""
    if _benign(exc):
        return
    if _seen_recently(_fingerprint(exc, None)):
        return
    text = build_error_message(exc=exc, context=context)
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
    if _seen_recently(_fingerprint(exc, record)):
        return
    text = build_error_message(record=record)
    await send_to_log_errors(text)
