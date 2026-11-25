# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Centralized error reporter: classifies, formats, dedupes, ships to LOG_ERRORS."""

from __future__ import annotations

import asyncio
import concurrent.futures
import contextlib
import re
import threading
import traceback
from itertools import islice
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

from pyrogram import Client
from pyrogram.errors import BadRequest, FloodWait, Forbidden, RPCError, Unauthorized

from tcbot import cfg
from tcbot.database import engine as db_engine
from tcbot.utils import logger as logger_mod
from tcbot.utils.circuit_breaker import CircuitOpenError
from tcbot.utils.logger import get_logger
from tcbot.utils.tasks import TaskTracker
from tcbot.utils.time_and_date import monotonic

if TYPE_CHECKING:
    import logging


log = get_logger("tcbot.error_reporter")


class PollingConflictError(RuntimeError):
    """Another process is already polling the same bot identity."""


# * Kurigram names Telegram failures differently from the old framework. The
# * reporter classifies by exception type, so keep one small local namespace
# * with the categories it needs.
_te = SimpleNamespace(
    RetryAfter=FloodWait,
    TimedOut=TimeoutError,
    Conflict=PollingConflictError,
    BadRequest=BadRequest,
    Forbidden=Forbidden,
    InvalidToken=Unauthorized,
    NetworkError=OSError,
    TelegramError=RPCError,
)

# * Log-noise patterns come from log_execution wrapping every handler.
_BENIGN_PATTERNS: tuple[str, ...] = (
    "message is not modified",
    "message to edit not found",
    "message to delete not found",
    "query is too old",
    "message is too old",
    "message can't be edited",
)
# * The tracer logs "… raised after Nms" only for an exception it is about to
# * re-raise. Match its whole shape so an unrelated error that merely mentions
# * elapsed time is still reported.
_LOG_NOISE_RE = re.compile(r"\[[^]]+\] uid=\S+ raised after [\d.]+ms")
_OWNER_ONLY_TYPES: tuple[type[BaseException], ...] = (_te.Conflict, _te.InvalidToken)
# * Kurigram raises these when the MTProto session must be re-established by
# * an operator; they are auth failures, not application code bugs.
_MTPROTO_AUTH_TYPES: tuple[str, ...] = (
    "AuthKeyDuplicated",
    "AuthKeyNotFound",
    "SessionRevoked",
)


def _benign(exc: BaseException | None) -> bool:
    """Check recoverable no-op (cancel, circuit, outage, known Telegram no-ops)."""
    if exc is None:
        return False
    if isinstance(exc, asyncio.CancelledError):
        return True
    if db_engine.is_connection_error(exc) or isinstance(exc, CircuitOpenError):
        return True
    # * A saturated pool is a load condition, not a defect. The circuit
    # * breaker reacts to it, and the handler logs it as a warning, so
    # * shipping a report per timeout would only bury the incidents that
    # * need an operator.
    if db_engine.is_pool_timeout(exc):
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
    """Check whether this is the tracer's duplicate of an already-reported error."""
    return bool(record) and bool(_LOG_NOISE_RE.search(record.getMessage()))


def _owner_only(exc: BaseException | None) -> bool:
    """Check owner-only routing to the owner DM only."""
    return exc is not None and isinstance(exc, _OWNER_ONLY_TYPES)


_ACTION_HINTS: tuple[tuple[str, str], ...] = (
    (
        "PostgreSQL Circuit Open",
        "PostgreSQL is unreachable; the circuit is open and calls fail fast "
        "until recovery. Check the database reachability and credentials, then retry.",
    ),
    ("[DB]", "Check PostgreSQL reachability and credentials, then retry the action."),
    ("Rate Limit", "Telegram asked to slow down; no action needed unless it persists."),
    ("Timed Out", "Transient Telegram hiccup; retry the action."),
    ("Polling Conflict", "Two bot instances are polling; stop the duplicate."),
    ("Invalid Token", "Token revoked or wrong; set BOT_TOKEN and restart."),
    ("Forbidden", "Client lacks admin rights in the target chat; re-promote it."),
    ("Bad Request", "Check the reported call arguments for a bad ID or text."),
    ("Network", "Transient connectivity issue; retry the action."),
    ("Timeout", "Operation exceeded its deadline; retry the action."),
    ("Code Bug", "Needs a code fix; see the traceback below."),
    ("[?] Unknown", "No exception attached; check the message and location above."),
    ("Circuit Open", "Telegram circuit is open; retry after the cooldown."),
    (
        "MTProto Auth",
        "MTProto auth key is dead; stop every instance, delete the session "
        "rows from mtproto_state, then boot one.",
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
    # * AuthKeyDuplicated subclasses RPCError in Kurigram; match dead keys
    # * before the generic branch so they keep the operator hint.
    if type(exc).__name__ in _MTPROTO_AUTH_TYPES:
        return "[~] MTProto Auth Key Invalidated"
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
    if db_engine.is_database_error(exc):
        return "[DB] Database Error"
    if isinstance(exc, CircuitOpenError):
        return (
            "[~] PostgreSQL Circuit Open"
            if "postgres" in str(exc).lower()
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
    return "[!] Code Bug"


# * Owner of the in-flight error deliveries. The logger handler calls the
# * sink synchronously, so the reporter schedules and tracks the delivery.
_report_tasks = TaskTracker("error report shipping")

# * Set once during post-init via attach(); owner_id refreshable via set_owner().
_bot: Client | None = None
_chat_id: int = 0
_thread_id: int | None = None
_owner_id: int = 0
# * The loop the reporter ships on. A log record can be emitted from a worker
# * thread such as the keep-alive server, where spawn() has no running loop;
# * the reporter hands that delivery to this loop instead of dropping it.
_loop: asyncio.AbstractEventLoop | None = None
_cross_thread: set[concurrent.futures.Future[None]] = set()


def attach(
    bot: Client, chat_id: int, thread_id: int | None, *, owner_id: int = 0
) -> None:
    """Inject bot, log channel, and owner DM target; zero chat falls back to owner DM."""
    global _bot, _chat_id, _thread_id, _owner_id, _loop
    _bot = bot
    try:
        _loop = asyncio.get_running_loop()
    except RuntimeError:
        _loop = None
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
    logger_mod.set_record_sink(_schedule_record)


async def _ship_record(record: logging.LogRecord) -> None:
    """Ship one log record to the error channel.

    The record already passed the dedupe gate in
    :func:`_schedule_record`, so the delivery only renders and sends it.
    """
    exc = record.exc_info[1] if record.exc_info else None
    await _deliver(exc, record)


def _schedule_record(record: logging.LogRecord) -> None:
    """Schedule the delivery of one log record to the error channel.

    The logger handler runs synchronously on the logging path, so the
    delivery is scheduled here and tracked for the shutdown drain. The
    reporter owns the delivery, so it also owns the delivery lifecycle.

    The dedupe decision is taken here, before the task is created: one
    task per error line would put the scan and the task creation on the
    event loop exactly when an incident floods it, and most error lines
    are duplicates that never ship.
    """
    if _bot is None:
        # * No bot yet: the record was emitted before the reporter was
        # * attached. There is nothing to ship it to.
        return
    if not _approved(record):
        return
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        # * A log record emitted from a worker thread has no running loop
        # * here. Hand the delivery to the loop the reporter was attached on
        # * instead of dropping it.
        loop = _loop
        if loop is not None and loop.is_running():
            # * The loop can close between is_running() and scheduling. Close
            # * the coroutine on that failure so it is never left unawaited.
            coro = _ship_record(record)
            try:
                future = asyncio.run_coroutine_threadsafe(coro, loop)
            except RuntimeError:
                coro.close()
                return
            _cross_thread.add(future)
            future.add_done_callback(_cross_thread_done)
            return
    _report_tasks.spawn(_ship_record(record))


def _cross_thread_done(future: concurrent.futures.Future[None]) -> None:
    """Drop a finished cross-thread delivery and surface its failure.

    A ``concurrent.futures.Future`` never warns about an unretrieved
    exception, so without this callback a delivery that raises outside the
    send guards disappears with no trace. Log at WARNING: ERROR records are
    routed back through this reporter and would recurse.
    """
    _cross_thread.discard(future)
    try:
        exc = future.exception()
    except concurrent.futures.CancelledError:
        return
    if exc is not None:
        log.warning("Cross-thread error delivery failed: %s", exc)


async def drain_pending() -> None:
    """Await the in-flight error deliveries at shutdown (bounded).

    A report already on thewire must not be cancelled: the cross-thread path
    below deliberately leaves pending deliveries running, and the same policy
    applies to the loop-thread tasks.
    """
    await _report_tasks.drain(cancel=False)
    live = [
        asyncio.wrap_future(future)
        for future in list(_cross_thread)
        if not future.done()
    ]
    if not live:
        return
    # * wait_for would cancel the gather on timeout and with it the wrapped
    # * futures, dropping deliveries the comment below only defers. wait()
    # * leaves pending deliveries running and still lets us retrieve the
    # * exceptions of the ones that finished.
    done, pending = await asyncio.wait(live, timeout=10)
    for task in done:
        if not task.cancelled():
            exc = task.exception()
            if exc is not None:
                log.debug("Cross-thread error delivery failed at shutdown: %s", exc)
    if pending:
        log.debug("Cross-thread error deliveries still running; leaving them.")


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
# * The logger sink runs on whatever thread emitted the record, including
# * the keep-alive server thread, while report_exc runs on the event loop.
# * Clients prune and mutate the dedupe maps, so their multi-step updates
# * share a lock instead of relying on the GIL for compound operations.
_dedupe_lock = threading.Lock()


def _owner_suppressed(fp: tuple[object, ...]) -> bool:
    """Check the hourly owner-DM budget for a fingerprint."""
    now = monotonic()
    with _dedupe_lock:
        if len(_owner_sent) >= _OWNER_MAX:
            for key in [
                k for k, (at, _) in _owner_sent.items() if now - at >= _OWNER_WINDOW
            ]:
                del _owner_sent[key]
            # * A burst of fresh fingerprints cannot be pruned by time. Drop
            # * the oldest tenth so the budget map stays bounded.
            if len(_owner_sent) >= _OWNER_MAX:
                oldest = sorted(_owner_sent, key=lambda key: _owner_sent[key][0])[
                    : max(1, _OWNER_MAX // 10)
                ]
                for key in oldest:
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
    """Report fp at most once per dedupe window; True when suppressed.

    The stored timestamp is the last *report*, not the last sighting.
    Refreshing it on every suppressed sighting would silence a frequent
    failure forever, because the entry could never age past the window.
    Keeping insertion order by report time preserves the front-pruning
    invariant without walking the whole map on every error line.
    """
    now = monotonic()
    with _dedupe_lock:
        while _recent:
            oldest = next(iter(_recent))
            if now - _recent[oldest] <= _DEDUPE_WINDOW:
                break
            del _recent[oldest]
        if len(_recent) >= _RECENT_MAX:
            # * The map is full of live fingerprints: drop the oldest tenth so
            # * the newest ones keep their slot.
            for key in list(islice(_recent, _RECENT_MAX // 10)):
                del _recent[key]
        if fp in _recent:
            # * Keep the last report time. Refreshing here would make a
            # * frequent failure never age out of the window.
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


# * No leading word boundary: a token inside "bot<token>/..." must still be
# * redacted when the exact configured value is unavailable.
_TOKEN_RE = re.compile(r"(?<!\d)\d{6,}:[A-Za-z0-9_-]{20,}\b")
_URL_CREDENTIALS_RE = re.compile(r"://(?:[^:@/\s]+)?:[^@/\s]+@")


def _scrub_secrets(text: str) -> str:
    """Redact exact configured values first, then credential-shaped patterns.

    A fatal startup report can run when the configuration itself failed to
    load. Reading ``cfg`` would raise again and mask the original error, so
    the configured-value pass degrades to the shape-based redaction below.
    """
    try:
        configured = (
            getattr(cfg, "bot_token", ""),
            getattr(cfg, "database_url", ""),
            getattr(cfg, "api_hash", ""),
            getattr(cfg, "redis_url", ""),
            getattr(cfg, "sentry_dsn", ""),
        )
    except Exception:
        configured = ()
    for secret in configured:
        if secret and secret in text:
            text = text.replace(secret, "[REDACTED]")
    text = _TOKEN_RE.sub("[REDACTED_TOKEN]", text)
    return _URL_CREDENTIALS_RE.sub("://[REDACTED]@", text)


def scrub_text(text: str) -> str:
    """Public wrapper for secret redaction of console-bound strings."""
    return _scrub_secrets(text)


def _scrub_event_value(value: object) -> object:
    """Recursively redact string leaves in a Sentry event payload."""
    if isinstance(value, str):
        return _scrub_secrets(value)
    if isinstance(value, dict):
        return {str(key): _scrub_event_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_scrub_event_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_scrub_event_value(item) for item in value)
    return value


def scrub_sentry_event(event: Any, hint: Any = None) -> Any:
    """Redact credential-bearing strings before a Sentry event is delivered.

    Used as the ``before_send`` hook, so non-string values such as retry
    counters must survive unchanged and the event structure must be kept.
    The SDK is an optional extra, so its ``Event`` type cannot be imported
    here without breaking checks in installations that omit it; the hook
    is duck-typed against the event mapping at runtime.
    """
    _ = hint
    return {key: _scrub_event_value(value) for key, value in event.items()}


def build_error_report_payload(
    *,
    exc: BaseException | None = None,
    record: logging.LogRecord | None = None,
    context: str | None = None,
) -> dict[str, Any]:
    """Build a rich error report with a collapsible details list.

    The short classification stays visible while the traceback and context
    live in an expandable block. Every dynamic value is redacted before it
    is placed in the rich HTML payload.
    """
    from tcbot.modules.helper.rich.formats import code, heading, pre  # noqa: PLC0415
    from tcbot.modules.helper.rich.list import bullet_list, details  # noqa: PLC0415
    from tcbot.modules.helper.rich.style import esc as html_esc  # noqa: PLC0415

    if record and record.exc_info and record.exc_info[1]:
        exc = exc or record.exc_info[1]
    label = _classify(exc)
    action = _action_hint(label)
    file_part, func_name, line_no = _location(exc, record)
    raw_msg = record.getMessage() if record else str(exc) if exc else "No detail."
    lines = [
        f"Type: {html_esc(label)}",
        f"Action: {html_esc(action)}",
        f"Where: {html_esc(f'{file_part}:{line_no} in {func_name}')}",
        f"Message: {html_esc(_scrub_secrets(raw_msg)[:_MAX_MSG])}",
    ]
    body = bullet_list(lines)
    if exc and exc.__traceback__:
        body += "\n" + html_esc("Traceback:") + pre(_scrub_secrets(_condensed_tb(exc)))
    if context:
        body += (
            "\n" + html_esc("Context:") + code(_scrub_secrets(str(context))[:_MAX_CTX])
        )
    return {
        "html": "\n".join((heading("Error Report", 2), details("<b>Details</b>", body)))
    }


# * At most _SEND_BUDGET per window; overflow counts into one summary.
_SEND_BUDGET: int = 20
_SEND_WINDOW: float = 60.0
_send_window_start: float = 0.0
_sent_in_window: int = 0
_suppressed_in_window: int = 0


async def _ship_throttled(payload: dict[str, Any]) -> None:
    """Send a rich report to LOG_ERRORS within budget, else count for summary."""
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
                from tcbot.modules.helper.rich.msg import (  # noqa: PLC0415
                    html_message,
                    send_rich,
                )

                await send_rich(
                    _bot,
                    _chat_id,
                    html_message(
                        f"Error reporter: {suppressed} further error(s) "
                        f"suppressed in the last {_SEND_WINDOW:.0f}s window."
                    ),
                    message_thread_id=_thread_id,
                )
            except Exception as exc:
                # * The summary is best effort: a failed send must not drop
                # * the current report that triggered this rollover.
                log.warning("Failed to ship error summary to LOG_ERRORS: %s", exc)
    if _sent_in_window >= _SEND_BUDGET:
        _suppressed_in_window += 1
        return
    _sent_in_window += 1
    try:
        from tcbot.modules.helper.rich.msg import send_rich  # noqa: PLC0415

        await send_rich(
            _bot,
            _chat_id,
            payload,
            message_thread_id=_thread_id,
        )
    except Exception as exc:
        log.warning("Failed to ship error to LOG_ERRORS: %s", exc)


async def send_to_log_errors(payload: dict[str, Any]) -> None:
    """Fire-and-forget rich report to LOG_ERRORS (throttled)."""
    if not _bot or not _chat_id:
        return
    await _ship_throttled(payload)


async def send_to_owner(payload: dict[str, Any]) -> None:
    """Fire-and-forget rich DM to the owner for infra-only errors."""
    if not _bot or not _owner_id:
        return
    try:
        from tcbot.modules.helper.rich.msg import send_rich  # noqa: PLC0415

        await send_rich(_bot, _owner_id, payload)
    except Exception as exc:
        log.warning("Failed to send owner DM: %s", exc)


async def _deliver(exc: BaseException | None, record: logging.LogRecord | None) -> None:
    """Render the report and send it to its destination."""
    payload = build_error_report_payload(exc=exc, record=record)
    if _owner_only(exc):
        await send_to_owner(payload)
    else:
        await send_to_log_errors(payload)


def _approved(record: logging.LogRecord) -> bool:
    """Return True when the record is worth shipping.

    Single owner of the delivery decision: the benign filter, the log
    noise filter, the dedupe window, and the owner-DM budget. The
    decision is taken on the logging path, before a task is created, so
    a flood of duplicate errors costs one map lookup instead of one task
    per line.
    """
    exc = record.exc_info[1] if record.exc_info else None
    if _is_benign(exc) or _log_noise(record) or _dedup(exc, record):
        return False
    if _owner_only(exc) and _owner_suppressed(
        _fingerprint_exc(exc) if exc is not None else _fingerprint_record(record)
    ):
        log.debug("Owner DM suppressed: budget spent.")
        return False
    return True


async def report_exc(exc: BaseException, context: str | None = None) -> None:
    """Report an exception; owner-only errors go to owner DM."""
    if _is_benign(exc) or _dedup(exc, None):
        return
    payload = build_error_report_payload(exc=exc, context=context)
    if _owner_only(exc):
        if _owner_suppressed(_fingerprint_exc(exc)):
            log.debug("Owner DM suppressed: budget spent.")
            return
        await send_to_owner(payload)
    else:
        await send_to_log_errors(payload)
