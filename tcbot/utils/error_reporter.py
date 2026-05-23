# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""Centralized error reporter — classifies, formats, and ships errors to LOG_ERRORS."""

from __future__ import annotations

import asyncio
import logging
import platform
import sys
import traceback
from typing import TYPE_CHECKING

import telegram.error as _te

from tcbot.utils.timedate_format import utc_now

if TYPE_CHECKING:
    from telegram import Bot

log = logging.getLogger(__name__)


# ─────────────────────── Module-Level State ─────────────────────── #
# * Set once during bot post-init via attach() — never mutated after that

_bot: "Bot | None" = None
_chat_id: int = 0
_thread_id: int | None = None


def attach(bot: "Bot", chat_id: int, thread_id: int | None) -> None:
    """Inject live bot instance and log channel config."""
    global _bot, _chat_id, _thread_id
    _bot = bot
    _chat_id = chat_id
    _thread_id = thread_id


# ────────────────────── Error Classification ────────────────────── #


def _classify(exc: BaseException | None) -> tuple[str, str]:
    """Categorize an exception into a human-readable label and slug."""
    if exc is None:
        return "[?] Unknown", "unknown"

    mod = type(exc).__module__ or ""

    if isinstance(exc, _te.RetryAfter):
        return "[~] Rate Limit - Flood Wait", "rate_limit"
    if isinstance(exc, _te.TimedOut):
        return "[~] Rate Limit - Timed Out", "rate_limit"
    if isinstance(exc, _te.NetworkError):
        return "[~] Telegram Network Error", "network"
    if isinstance(exc, _te.TelegramError):
        return "[!] Telegram API Error", "telegram_api"

    if any(x in mod for x in ("motor", "pymongo", "mongo")):
        return "[DB] Database Error", "database"

    if isinstance(exc, (ConnectionError, TimeoutError, OSError)) or any(
        x in mod for x in ("httpx", "aiohttp", "urllib3", "ssl")
    ):
        return "[~] Network / Server Error", "network"

    if isinstance(exc, asyncio.TimeoutError):
        return "[~] Async Timeout", "async_timeout"

    if isinstance(exc, asyncio.CancelledError):
        return "[-] Task Cancelled", "cancelled"

    return "[!] Code Bug", "code_bug"


# ─────────────────────── Message Formatting ─────────────────────── #

_MAX_TB = 3000
_MAX_MSG = 500


def _esc(s: str) -> str:
    """Escape HTML special characters for Telegram HTML parse mode."""
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _trim_tb(tb_str: str) -> str:
    """Trim traceback to _MAX_TB characters, prepending an ellipsis marker."""
    if len(tb_str) > _MAX_TB:
        return "…(trimmed)\n" + tb_str[-_MAX_TB:]
    return tb_str


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
        raw_path = record.pathname.replace("\\", "/")
        module_path = (
            raw_path.split("tcbot/")[-1] if "tcbot/" in raw_path else record.name
        )
        func_name = record.funcName
        line_no = record.lineno
        raw_msg = record.getMessage()
    elif exc and exc.__traceback__:
        frames = traceback.extract_tb(exc.__traceback__)
        last = frames[-1] if frames else None
        if last:
            raw_path = last.filename.replace("\\", "/")
            module_path = (
                raw_path.split("tcbot/")[-1] if "tcbot/" in raw_path else raw_path
            )
            func_name = last.name
            line_no = last.lineno
        else:
            module_path = type(exc).__module__
            func_name = "?"
            line_no = 0
        raw_msg = str(exc)
    else:
        module_path = "?"
        func_name = "?"
        line_no = 0
        raw_msg = "No detail available."

    label, _ = _classify(exc)

    tb_block = ""
    if exc and exc.__traceback__:
        tb_block = f"\n\n<b>Traceback:</b>\n<pre>{_esc(_trim_tb(traceback.format_exc()))}</pre>"
    elif record and record.exc_info and record.exc_info[0]:
        tb_block = f"\n\n<b>Traceback:</b>\n<pre>{_esc(_trim_tb(''.join(traceback.format_exception(*record.exc_info))))}</pre>"

    ctx_block = ""
    if context:
        ctx_block = f"\n\n<b>Context:</b>\n<code>{_esc(str(context)[:400])}</code>"

    py_ver = sys.version.split()[0]
    host = platform.node() or "?"

    return (
        f"<b>[ ERROR REPORT ]</b>\n"
        f"&#9472;&#9472;&#9472;&#9472;&#9472;&#9472;&#9472;&#9472;&#9472;&#9472;&#9472;&#9472;&#9472;\n"
        f"<b>Type:</b> {label}\n"
        f"<b>File:</b> <code>{_esc(module_path)}</code>\n"
        f"<b>Func:</b> <code>{_esc(func_name)}</code>\n"
        f"<b>Line:</b> <code>{line_no}</code>\n"
        f"<b>Time:</b> {time_str} | {date_str}\n"
        f"<b>Python:</b> {py_ver} @ {_esc(host)}\n"
        f"&#9472;&#9472;&#9472;&#9472;&#9472;&#9472;&#9472;&#9472;&#9472;&#9472;&#9472;&#9472;&#9472;\n"
        f"<b>Error:</b>\n<code>{_esc(raw_msg[:_MAX_MSG])}</code>"
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
        print(
            f"[error_reporter] Failed to ship error to Telegram: {exc}", file=sys.stderr
        )


# ────────────────────── Convenience Wrappers ────────────────────── #


async def report_exc(
    exc: BaseException,
    context: str | None = None,
) -> None:
    """Report an exception with optional context string."""
    text = build_error_message(exc=exc, context=context)
    await send_to_log_errors(text)


async def report_record(record: logging.LogRecord) -> None:
    """Report a logging.LogRecord (from log.error() / log.critical())."""
    text = build_error_message(record=record)
    await send_to_log_errors(text)
