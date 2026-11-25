# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Error report lifecycle: state, dedupe, rendering, throttling, and delivery."""

from __future__ import annotations

import asyncio
import concurrent.futures
import contextlib
import re
import threading
import traceback
from itertools import islice
from typing import TYPE_CHECKING, Any

from pyrogram import Client

from tcbot.modules.helper.pipelines.errors.classify import (
    _action_hint,
    _classify,
    _is_benign,
    _log_noise,
    _owner_only,
)
from tcbot.modules.helper.pipelines.errors.exceptions import PollingConflictError
from tcbot.modules.helper.pipelines.errors.redaction import (
    _scrub_secrets,
    scrub_sentry_event,
    scrub_text,
)
from tcbot.utils import logger as logger_mod
from tcbot.utils.logger import get_logger
from tcbot.utils.tasks import TaskTracker
from tcbot.utils.time_and_date import monotonic

if TYPE_CHECKING:
    import logging

log = get_logger("tcbot.error_reporter")

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
    """Check the hourly owner-DM budget without charging it.

    The budget is charged only after a confirmed delivery. Charging at
    decision time let three failed DMs burn the whole hourly window, so a
    recovered Telegram still could not deliver a polling conflict or an
    invalid-token alert.
    """
    now = monotonic()
    with _dedupe_lock:
        _prune_owner_sent(now)
        start, count = _owner_sent.get(fp, (now, 0))
        return now - start < _OWNER_WINDOW and count >= _OWNER_BUDGET


def _prune_owner_sent(now: float) -> None:
    """Keep the owner budget map bounded; caller holds ``_dedupe_lock``."""
    if len(_owner_sent) < _OWNER_MAX:
        return
    for key in [k for k, (at, _) in _owner_sent.items() if now - at >= _OWNER_WINDOW]:
        del _owner_sent[key]
    # * A burst of fresh fingerprints cannot be pruned by time. Drop the
    # * oldest tenth so the budget map stays bounded.
    if len(_owner_sent) >= _OWNER_MAX:
        oldest = sorted(_owner_sent, key=lambda key: _owner_sent[key][0])[
            : max(1, _OWNER_MAX // 10)
        ]
        for key in oldest:
            del _owner_sent[key]


def _owner_record_sent(fp: tuple[object, ...]) -> None:
    """Charge one delivered owner DM to the fingerprint's hourly budget."""
    now = monotonic()
    with _dedupe_lock:
        _prune_owner_sent(now)
        start, count = _owner_sent.get(fp, (now, 0))
        if now - start >= _OWNER_WINDOW:
            start, count = now, 0
        _owner_sent[fp] = (start, count + 1)


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
    from tcbot.modules.helper.rich.style import bold  # noqa: PLC0415
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
    if exc is not None:
        # * A failure built from stored delivery details has no traceback, but
        # * _condensed_tb still renders its type and message. Skipping the
        # * block here hid the actual Telegram error from the operator.
        body += "\n" + html_esc("Traceback:") + pre(_scrub_secrets(_condensed_tb(exc)))
    if context:
        body += (
            "\n" + html_esc("Context:") + code(_scrub_secrets(str(context))[:_MAX_CTX])
        )
    return {
        "html": "\n".join((heading("Error Report", 2), details(bold("Details"), body)))
    }


# * At most _SEND_BUDGET per window; overflow counts into one summary.
_SEND_BUDGET: int = 20
_SEND_WINDOW: float = 60.0
_send_window_start: float = 0.0
_sent_in_window: int = 0
_suppressed_in_window: int = 0
# * Deliveries run as separate tasks on one loop, and the reporter also
# * accepts cross-thread hand-off. The window counters are read and reserved
# * under this lock so concurrent reports cannot claim the same budget slot.
# * The lock is never held across an await.
_send_lock = threading.Lock()


async def _ship_throttled(payload: dict[str, Any]) -> None:
    """Send a rich report to LOG_ERRORS within budget, else count for summary.

    The window decision and the slot reservation are atomic. A failed send
    releases its slot and adds the incident to the next rollover summary so
    neither the budget nor the incident count is lost.
    """
    global _send_window_start, _sent_in_window, _suppressed_in_window
    if not _bot or not _chat_id:
        return
    summary: str | None = None
    suppressed_count: int = 0
    reserved_window: float = 0.0
    with _send_lock:
        now = monotonic()
        if now - _send_window_start >= _SEND_WINDOW:
            _send_window_start = now
            _sent_in_window = 0
            if _suppressed_in_window:
                suppressed_count = _suppressed_in_window
                summary = (
                    f"Error reporter: {suppressed_count} further error(s) "
                    f"suppressed in the last {_SEND_WINDOW:.0f}s window."
                )
                _suppressed_in_window = 0
        if _sent_in_window >= _SEND_BUDGET:
            _suppressed_in_window += 1
            return
        # * Reserve before the await; a failed send releases the slot below
        # * only if the window has not rolled over while it was in flight.
        _sent_in_window += 1
        reserved_window = _send_window_start

    from tcbot.modules.helper.rich.msg import (  # noqa: PLC0415
        html_message,
        send_rich,
    )

    if summary is not None:
        try:
            await send_rich(
                _bot,
                _chat_id,
                html_message(summary),
                message_thread_id=_thread_id,
            )
        except Exception as exc:
            # * The summary is best effort, but its count is not: a failed
            # * rollover send must not erase the incidents it summarised.
            log.warning("Failed to ship error summary to LOG_ERRORS: %s", exc)
            with _send_lock:
                _suppressed_in_window += suppressed_count

    try:
        await send_rich(
            _bot,
            _chat_id,
            payload,
            message_thread_id=_thread_id,
        )
    except Exception as exc:
        # * A report that never reached Telegram is not a sent report: it
        # * releases its reserved slot and stays in the rollover count.
        log.warning("Failed to ship error to LOG_ERRORS: %s", exc)
        with _send_lock:
            if _send_window_start == reserved_window:
                _sent_in_window -= 1
            _suppressed_in_window += 1


async def send_to_log_errors(payload: dict[str, Any]) -> None:
    """Fire-and-forget rich report to LOG_ERRORS (throttled)."""
    if not _bot or not _chat_id:
        return
    await _ship_throttled(payload)


async def send_to_owner(
    payload: dict[str, Any], fp: tuple[object, ...] | None = None
) -> None:
    """Fire-and-forget rich DM to the owner for infra-only errors.

    A fingerprint is charged only after the send lands. A failed DM must not
    spend the hourly budget, or a recovered Telegram still cannot deliver the
    next polling-conflict or invalid-token alert.
    """
    if not _bot or not _owner_id:
        return
    try:
        from tcbot.modules.helper.rich.msg import send_rich  # noqa: PLC0415

        await send_rich(_bot, _owner_id, payload)
    except Exception as exc:
        log.warning("Failed to send owner DM: %s", exc)
        return
    if fp is not None:
        _owner_record_sent(fp)


async def _deliver(exc: BaseException | None, record: logging.LogRecord | None) -> None:
    """Render the report and send it to its destination."""
    payload = build_error_report_payload(exc=exc, record=record)
    if _owner_only(exc):
        fp = (
            _fingerprint_exc(exc) if exc is not None else _fingerprint_record(record)  # type: ignore[arg-type]
        )
        await send_to_owner(payload, fp)
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
        fp = _fingerprint_exc(exc)
        if _owner_suppressed(fp):
            log.debug("Owner DM suppressed: budget spent.")
            return
        await send_to_owner(payload, fp)
    else:
        await send_to_log_errors(payload)


__all__ = [
    "PollingConflictError",
    "attach",
    "build_error_report_payload",
    "drain_pending",
    "report_exc",
    "scrub_sentry_event",
    "scrub_text",
    "send_to_log_errors",
    "send_to_owner",
    "set_owner",
]
