# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
## Centralized error reporter — classifies, formats, and ships errors to LOG_ERRORS
##
## Three automatic coverage layers (no per-file changes needed):
##   1. TelegramErrorHandler on the root logger  → catches every log.error() / log.critical()
##   2. PTB application.add_error_handler()      → catches all unhandled handler exceptions
##   3. asyncio loop.set_exception_handler()     → catches background-task / create_task() failures
from __future__ import annotations

import asyncio
import logging
import platform
import sys
import traceback
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import telegram.error as _te

if TYPE_CHECKING:
    from telegram import Bot, Update
    from telegram.ext import ContextTypes

log = logging.getLogger(__name__)

## ── module-level state (set once in _post_init via attach()) ─────────────────

_bot:       "Bot | None" = None
_chat_id:   int          = 0
_thread_id: int | None   = None


def attach(bot: "Bot", chat_id: int, thread_id: int | None) -> None:
    """Inject the live bot and LOG_ERRORS destination. Called from post_init."""
    global _bot, _chat_id, _thread_id
    _bot       = bot
    _chat_id   = chat_id
    _thread_id = thread_id


## ── error classification ─────────────────────────────────────────────────────

def _classify(exc: BaseException | None) -> tuple[str, str]:
    """Return (display_label, slug) describing the error source."""
    if exc is None:
        return "[?] Unknown", "unknown"

    mod = type(exc).__module__ or ""

    if isinstance(exc, _te.RetryAfter):
        return "[~] Rate Limit — Flood Wait", "rate_limit"
    if isinstance(exc, _te.TimedOut):
        return "[~] Rate Limit — Timed Out", "rate_limit"
    if isinstance(exc, _te.NetworkError):
        return "[~] Telegram Network Error", "network"
    if isinstance(exc, _te.TelegramError):
        return "[!] Telegram API Error", "telegram_api"

    if any(x in mod for x in ("motor", "pymongo", "mongo")):
        return "[DB] Database Error", "database"

    if (
        isinstance(exc, (ConnectionError, TimeoutError, OSError))
        or any(x in mod for x in ("httpx", "aiohttp", "urllib3", "ssl"))
    ):
        return "[~] Network / Server Error", "network"

    if isinstance(exc, asyncio.TimeoutError):
        return "[~] Async Timeout", "async_timeout"

    if isinstance(exc, asyncio.CancelledError):
        return "[-] Task Cancelled", "cancelled"

    return "[!] Code Bug", "code_bug"


## ── message formatter ────────────────────────────────────────────────────────

_MAX_TB   = 3000
_MAX_MSG  = 500


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def build_error_message(
    *,
    exc:     BaseException | None      = None,
    record:  logging.LogRecord | None  = None,
    context: str | None                = None,
) -> str:
    """Return a formatted HTML error message ready to send to Telegram."""
    now      = datetime.now(timezone.utc)
    time_str = now.strftime("%H:%M:%S UTC")
    date_str = now.strftime("%d-%m-%Y")

    ## ── resolve exc from record if not provided explicitly ───────────────────
    if record and record.exc_info and record.exc_info[1]:
        exc = exc or record.exc_info[1]

    ## ── source location ──────────────────────────────────────────────────────
    if record:
        ## direct log.error() call — record has exact location
        raw_path    = record.pathname.replace("\\", "/")
        module_path = raw_path.split("tcbot/")[-1] if "tcbot/" in raw_path else record.name
        func_name   = record.funcName
        line_no     = record.lineno
        raw_msg     = record.getMessage()
    elif exc and exc.__traceback__:
        frames = traceback.extract_tb(exc.__traceback__)
        last   = frames[-1] if frames else None
        if last:
            raw_path    = last.filename.replace("\\", "/")
            module_path = raw_path.split("tcbot/")[-1] if "tcbot/" in raw_path else raw_path
            func_name   = last.name
            line_no     = last.lineno
        else:
            module_path = type(exc).__module__
            func_name   = "?"
            line_no     = 0
        raw_msg = str(exc)
    else:
        module_path = "?"
        func_name   = "?"
        line_no     = 0
        raw_msg     = "No detail available."

    label, _ = _classify(exc)

    ## ── traceback block ───────────────────────────────────────────────────────
    tb_block = ""
    if exc and exc.__traceback__:
        tb_str = traceback.format_exc()
        if len(tb_str) > _MAX_TB:
            tb_str = "…(trimmed)\n" + tb_str[-_MAX_TB:]
        tb_block = f"\n\n<b>Traceback:</b>\n<pre>{_esc(tb_str)}</pre>"
    elif record and record.exc_info and record.exc_info[0]:
        tb_str = "".join(traceback.format_exception(*record.exc_info))
        if len(tb_str) > _MAX_TB:
            tb_str = "…(trimmed)\n" + tb_str[-_MAX_TB:]
        tb_block = f"\n\n<b>Traceback:</b>\n<pre>{_esc(tb_str)}</pre>"

    ## ── optional update / context block ──────────────────────────────────────
    ctx_block = ""
    if context:
        ctx_block = f"\n\n<b>Context:</b>\n<code>{_esc(str(context)[:400])}</code>"

    py_ver = sys.version.split()[0]
    host   = platform.node() or "?"

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


## ── low-level send ───────────────────────────────────────────────────────────

async def send_to_log_errors(text: str) -> None:
    """Fire-and-forget send to the LOG_ERRORS channel. Never raises."""
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
        ## Use print so we don't risk recursive logging
        print(f"[error_reporter] Failed to ship error to Telegram: {exc}", file=sys.stderr)


## ── convenience wrappers ─────────────────────────────────────────────────────

async def report_exc(
    exc:     BaseException,
    context: str | None = None,
) -> None:
    """Build and ship an exception report. Called by the PTB and asyncio handlers."""
    text = build_error_message(exc=exc, context=context)
    await send_to_log_errors(text)


async def report_record(record: logging.LogRecord) -> None:
    """Build and ship a logging.LogRecord report. Called by TelegramErrorHandler."""
    text = build_error_message(record=record)
    await send_to_log_errors(text)
