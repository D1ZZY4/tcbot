# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Scheduler lifecycle: start, stop, and readiness."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from tcbot.database import scheduler as _sched_pkg
from tcbot.utils.logger import get_logger

if TYPE_CHECKING:
    from telegram import Bot

# * Logger keeps the pre-split name so log output is unchanged.
log = get_logger("tcbot.database.scheduler")


async def start(
    mongodb_uri: str,
    db_name: str,
    warn_expiry_days: int,
    *,
    bot: Bot | None = None,
    sync_interval_hours: int = 0,
) -> None:
    """Initialise and start the APScheduler background scheduler.

    Spawns a dedicated asyncio task that calls ``scheduler.start()`` inside the
    running event loop.  Uses ``MongoDBJobStore`` so all schedules and job state
    survive bot restarts.

    Blocks until the scheduler is ready to accept schedule operations.

    Args:
        mongodb_uri: MongoDB connection string (same as ``MONGODB_URI``).
        db_name: MongoDB database name (same as ``DB_NAME``).
        warn_expiry_days: Days after which warn_counts are expired (0 = disabled).
        bot: Live bot for the optional enforcement-sync sweep (same as
            ``SYNC_INTERVAL_HOURS``); ``None`` disables the sweep.
        sync_interval_hours: Hours between enforcement sweeps (0 = disabled).

    """
    # * A live task means start() already ran: a second start would orphan
    # * the first scheduler and duplicate every job. Refuse loudly.
    if _sched_pkg._sched_task is not None and not _sched_pkg._sched_task.done():
        raise RuntimeError("APScheduler already started.")
    _sched_pkg._sched_ready = asyncio.Event()
    _sched_pkg._sched_stop = asyncio.Event()
    _sched_pkg._sched_error = None
    _sched_pkg._sync_bot = bot
    _sched_pkg._sched_task = asyncio.create_task(
        _sched_pkg._scheduler_background(
            mongodb_uri, db_name, warn_expiry_days, sync_interval_hours
        ),
        name="tcbot.scheduler",
    )
    try:
        await asyncio.wait_for(
            _sched_pkg._sched_ready.wait(), timeout=_sched_pkg._STOP_TIMEOUT_S
        )
    except asyncio.CancelledError:
        # * Shutdown raced startup: cancel the background task, wait for it
        # * to unwind, clear the globals, then propagate so the next start()
        # * sees clean state instead of a leaked half-started scheduler.
        if _sched_pkg._sched_task is not None and not _sched_pkg._sched_task.done():
            _sched_pkg._sched_task.cancel()
            await asyncio.gather(_sched_pkg._sched_task, return_exceptions=True)
        _sched_pkg._sched_task = None
        _sched_pkg._sched_ready = None
        _sched_pkg._sched_stop = None
        _sched_pkg._sched_error = None
        raise
    except TimeoutError:
        # * The background task did not signal readiness within the grace
        # * window (constructor raise before the try, or a hung jobstore
        # * handshake). Cancel it and unwind bounded so a task ignoring
        # * cancellation cannot hang start beyond the outer bound.
        _sched_pkg._sched_error = TimeoutError(
            f"APScheduler did not become ready within {_sched_pkg._STOP_TIMEOUT_S:.0f}s."
        )
        if _sched_pkg._sched_task is not None and not _sched_pkg._sched_task.done():
            _sched_pkg._sched_task.cancel()
            try:
                await asyncio.wait_for(
                    asyncio.gather(_sched_pkg._sched_task, return_exceptions=True),
                    timeout=2.0,
                )
            except TimeoutError:
                log.warning("APScheduler startup task ignored cancellation.")
    if _sched_pkg._sched_error is not None:
        startup_error = _sched_pkg._sched_error
        if _sched_pkg._sched_task is not None:
            try:
                await asyncio.wait_for(
                    asyncio.gather(_sched_pkg._sched_task, return_exceptions=True),
                    timeout=2.0,
                )
            except TimeoutError:
                log.warning("APScheduler startup task ignored cancellation.")
        _sched_pkg._sched_task = None
        _sched_pkg._sched_ready = None
        _sched_pkg._sched_stop = None
        _sched_pkg._sched_error = None
        raise RuntimeError("APScheduler failed to start.") from startup_error
    log.info("APScheduler ready (MongoDBJobStore → %s).", db_name)


async def stop() -> None:
    """Stop the scheduler and release all resources.

    Sets the stop event so the background task can exit cleanly.
    Safe to call even if :func:`start` was never called.
    """
    if _sched_pkg._sched_stop is not None:
        _sched_pkg._sched_stop.set()
    if _sched_pkg._sched_task is not None:
        try:
            await asyncio.wait_for(
                _sched_pkg._sched_task, timeout=_sched_pkg._STOP_TIMEOUT_S
            )
        except TimeoutError:
            log.warning(
                "APScheduler background task did not stop within %.0fs.",
                _sched_pkg._STOP_TIMEOUT_S,
            )
            # * A stuck task left running would own a second live scheduler
            # * next start(): cancel it so shutdown never orphans execution.
            # * wait_for already gave up awaiting; cancel only signals.
            if not _sched_pkg._sched_task.done():
                _sched_pkg._sched_task.cancel()
                # * Best-effort unwind so task exceptions are retrieved and
                # * the next start() does not race a dying task. Bounded:
                # * a task that ignores cancellation is left to the loop.
                try:
                    await asyncio.wait_for(
                        asyncio.gather(_sched_pkg._sched_task, return_exceptions=True),
                        timeout=2.0,
                    )
                except TimeoutError:
                    log.warning("APScheduler stuck task ignored cancellation.")
    _sched_pkg._sched_task = None
    _sched_pkg._sched_ready = None
    _sched_pkg._sched_stop = None
    _sched_pkg._sched_error = None
    _sched_pkg._sync_bot = None
    log.info("APScheduler stopped.")


def is_ready() -> bool:
    """Return True only after scheduler startup has completed successfully."""
    return (
        _sched_pkg._scheduler is not None
        and _sched_pkg._sched_ready is not None
        and _sched_pkg._sched_ready.is_set()
        and _sched_pkg._sched_error is None
    )
