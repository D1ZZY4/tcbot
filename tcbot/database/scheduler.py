# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Persistent moderation scheduler backed by APScheduler 3.x + MongoDB."""

from __future__ import annotations

import asyncio
import contextlib
from datetime import timedelta
from typing import TYPE_CHECKING

from apscheduler.jobstores.mongodb import MongoDBJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

# * Direct module imports (not through tcbot.database.__init__) to avoid circular
# * imports: tcbot.database.__init__ → scheduler → tcbot.database.__init__
from tcbot.database.mongos import col as _col
from tcbot.database.mongos import db_call as _db_call
from tcbot.database.mongos import (
    mongo_client_kwargs as _mongo_client_kwargs,
)
from tcbot.database.mongos import (
    mongo_jobstore_kwargs as _mongo_jobstore_kwargs,
)
from tcbot.utils.dispatch import throw_if_cancelled
from tcbot.utils.logger import get_logger
from tcbot.utils.time_and_date import utc_now

if TYPE_CHECKING:
    from telegram import Bot

log = get_logger(__name__)

# ──────────────── Recurring job schedule IDs ──────────────────── #
# * Stable IDs prevent duplicate schedules across restarts.
# * (replace_existing=True updates the trigger without creating duplicates)

_WARN_EXPIRY_SCHEDULE_ID: str = "tcbot.warn_expiry_daily"
# * Stable ID for the optional enforcement-sync sweep (/tcsync core on a
# * timer). Same replace_existing idempotency as the warn-expiry schedule.
_SYNC_SCHEDULE_ID: str = "tcbot.enforcement_sync"
# * Legacy ID kept so _register_periodic_schedules can remove the old schedule
# * from any MongoDB datastore that was created before the TTL-index migration.
_CLEANUP_SCHEDULE_ID: str = "tcbot.db_cleanup_weekly"

# * Maximum seconds to wait for the scheduler background task to exit cleanly
# * before declaring it stuck.  10 s matches the PTB shutdown grace window.
_STOP_TIMEOUT_S: float = 10.0
# * Ceiling for one warn-expiry delete batch: a hung MongoDB must fail the
# * run loudly instead of wedging the scheduler worker forever.
_EXPIRE_OP_TIMEOUT_S: float = 60.0
# * Ceiling for one scheduled enforcement sweep: a hung sync must end and
# * let the next interval re-drive instead of wedging the job.
_SYNC_RUN_TIMEOUT_S: float = 300.0

# ──────────────── Module-level scheduler state ──────────────────── #
# * _scheduler:   live AsyncIOScheduler reference (set inside background task)
# * _sched_task:  the asyncio Task that runs scheduler.start() + stop wait
# * _sched_ready: event set when the scheduler is initialised and available
# * _sched_stop:  event set by stop() to trigger graceful shutdown
# * _sched_error: captured exception if background task crashes
# * _sync_bot: live Bot for the scheduled sync sweep (set via start(bot=...));
# * None disables the sweep even when an interval is configured.

_scheduler: AsyncIOScheduler | None = None
_sched_task: asyncio.Task[None] | None = None
_sched_ready: asyncio.Event | None = None
_sched_stop: asyncio.Event | None = None
_sched_error: BaseException | None = None
_sync_bot: Bot | None = None


# ══════════════════════════════════════════════════════════════════ #
#  Persistent job functions
#  Must be module-level callables so APScheduler can serialise their
#  import paths into MongoDB and call them after bot restarts.
# ══════════════════════════════════════════════════════════════════ #


async def expire_old_warns(warn_expiry_days: int) -> None:
    """Delete expired warn records from both ``warns`` and ``warn_counts``.

    Both collections must be pruned together. Deleting only ``warn_counts``
    leaves individual ``warns`` documents intact; ``_sync_warn_count`` then
    reconstructs the counter from those documents on the next warn operation,
    making expiry a no-op. Deleting both collections atomically (in parallel)
    prevents this backfill from restoring stale counts.

    Called daily by APScheduler when ``WARN_EXPIRY_DAYS > 0``, or on demand by
    the serverless cron endpoint (``api/cron.py`` on Vercel) which cannot run
    a persistent scheduler.

    A non-positive ``warn_expiry_days`` is a no-op: without this guard the
    cutoff would equal now and the deletes below would wipe every warn.
    """
    if warn_expiry_days <= 0:
        log.info(
            "Warn expiry skipped: WARN_EXPIRY_DAYS=%d disables expiry.",
            warn_expiry_days,
        )
        return
    cutoff = utc_now() - timedelta(days=warn_expiry_days)
    try:
        async with asyncio.timeout(_EXPIRE_OP_TIMEOUT_S):
            counts_res, warns_res = await asyncio.gather(
                _db_call(
                    _col("warn_counts").delete_many({"updated_at": {"$lt": cutoff}})
                ),
                _db_call(_col("warns").delete_many({"timestamp": {"$lt": cutoff}})),
                return_exceptions=True,
            )
    except TimeoutError:
        log.exception(
            "Warn expiry timed out after %ds; no expiry completed.",
            _EXPIRE_OP_TIMEOUT_S,
        )
        return
    # ! CRITICAL: a cancelled expiry must propagate, not report success.
    throw_if_cancelled((counts_res, warns_res))
    if isinstance(counts_res, BaseException):
        log.error("Warn expiry: warn_counts delete failed: %s", counts_res)
    if isinstance(warns_res, BaseException):
        log.error("Warn expiry: warns delete failed: %s", warns_res)
    counts_del = (
        counts_res.deleted_count if not isinstance(counts_res, BaseException) else 0
    )
    warns_del = (
        warns_res.deleted_count if not isinstance(warns_res, BaseException) else 0
    )
    if isinstance(counts_res, BaseException) or isinstance(warns_res, BaseException):
        log.error(
            "Warn expiry incomplete: removed %d warn_count and %d warn records older than %d days; see errors above.",
            counts_del,
            warns_del,
            warn_expiry_days,
        )
    else:
        log.info(
            "Warn expiry: removed %d warn_count and %d warn records older than %d days.",
            counts_del,
            warns_del,
            warn_expiry_days,
        )


async def _cleanup_old_records() -> None:
    """No-op migration shim for the retired weekly member_cache cleanup job.

    member_cache cleanup is now handled automatically by the MongoDB TTL index on
    ``last_updated`` (``expireAfterSeconds=_MEMBER_CACHE_EXPIRE_S``, 90 days), added
    in ``mongos.ensure_indexes()``.  The APScheduler schedule is removed on startup
    in ``_register_periodic_schedules``; this function exists solely so that any
    schedule record persisted from a previous bot version can be deserialised and
    called without raising an ``AttributeError``.  It is safe to remove once all
    running instances have been restarted and the MongoDB datastore no longer contains
    the ``tcbot.db_cleanup_weekly`` schedule entry.
    """
    log.info(
        "DB cleanup job called but is now a no-op; "
        "cleanup is handled by the MongoDB TTL index on member_cache.last_updated."
    )


async def _run_scheduled_sync() -> None:
    """Run one bounded enforcement sweep (the ``/tcsync`` core on a timer).

    Module-level so APScheduler can serialise its import path into MongoDB.
    Results go to the log only: there is no operator message to edit here.
    A missing bot (or any failure) logs and returns; the next interval
    re-drives, so one bad run never wedges the schedule.
    """
    # * Lazy import: tcbot.modules.* must never be imported at this module's
    # * top level (database/__init__ → scheduler → modules → database cycle).
    from tcbot.modules import syncing as _syncing  # noqa: PLC0415

    bot = _sync_bot
    if bot is None:
        log.debug("Scheduled sync skipped: no bot reference.")
        return
    try:
        async with asyncio.timeout(_SYNC_RUN_TIMEOUT_S):
            counts = await _syncing.run_ban_sync(bot)
    except TimeoutError:
        log.exception(
            "Scheduled enforcement sync timed out after %ds; next interval re-drives.",
            _SYNC_RUN_TIMEOUT_S,
        )
        return
    except Exception:
        log.exception("Scheduled enforcement sync failed.")
        return
    log.info(
        "Scheduled enforcement sync: checked=%d enforced=%d skipped=%d failed=%d truncated=%s.",
        counts.checked,
        counts.enforced_bans,
        counts.skipped,
        counts.failed,
        counts.truncated,
    )


async def _scheduler_background(
    mongodb_uri: str,
    db_name: str,
    warn_expiry_days: int,
    sync_interval_hours: int = 0,
) -> None:
    """Long-running background task that owns the AsyncIOScheduler lifecycle.

    Calls ``scheduler.start()`` (synchronous, must be in the running event loop),
    registers periodic schedules, then waits for the stop event before calling
    ``scheduler.shutdown()``.
    """
    global _scheduler, _sched_error
    # * MongoDBJobStore builds its own synchronous MongoClient, so it needs
    # * the same certifi TLS pinning as the Motor client: without it, Atlas
    # * handshakes fail with CERTIFICATE_VERIFY_FAILED on sandboxes whose
    # * system CA store is stale, while Motor connects fine. Extra kwargs
    # * flow straight into pymongo.MongoClient (supported by APScheduler 3.x).
    jobstores = {
        "mongodb": MongoDBJobStore(
            database=db_name,
            host=mongodb_uri,
            **_mongo_client_kwargs(),
            **_mongo_jobstore_kwargs(),
        )
    }
    scheduler = AsyncIOScheduler(jobstores=jobstores)
    _scheduler = scheduler
    started = False
    try:
        _register_periodic_schedules(
            scheduler, warn_expiry_days, sync_interval_hours=sync_interval_hours
        )
        scheduler.start()
        started = True
        if _sched_ready is None:
            raise RuntimeError(
                "_sched_ready event not initialised before _scheduler_background ran"
            )
        if _sched_stop is None:
            raise RuntimeError(
                "_sched_stop event not initialised before _scheduler_background ran"
            )
        # Signal readiness only after the recurring schedules are registered
        # and the scheduler has accepted background execution.
        _sched_ready.set()
        await _sched_stop.wait()
        scheduler.shutdown(wait=False)
        started = False
    except Exception as exc:
        log.exception("APScheduler background task crashed.")
        _sched_error = exc
        if _sched_ready is not None and not _sched_ready.is_set():
            _sched_ready.set()  # unblock start() so it doesn't hang forever
    finally:
        # * A crash or cancellation past start() must still release the
        # * scheduler and its synchronous MongoClient; otherwise the
        # * process leaks both while reporting itself stopped.
        if started:
            with contextlib.suppress(Exception):
                scheduler.shutdown(wait=False)
        _scheduler = None
        log.info("APScheduler background task exited.")


# ══════════════════════════════════════════════════════════════════ #
#  Periodic schedule registration
# ══════════════════════════════════════════════════════════════════ #


def _register_periodic_schedules(
    scheduler: AsyncIOScheduler, warn_expiry_days: int, *, sync_interval_hours: int = 0
) -> None:
    """Register recurring maintenance schedules (idempotent via replace_existing)."""
    if warn_expiry_days > 0:
        scheduler.add_job(
            expire_old_warns,
            trigger=IntervalTrigger(hours=24),
            id=_WARN_EXPIRY_SCHEDULE_ID,
            args=[warn_expiry_days],
            replace_existing=True,
            # * A restart straddling the daily fire must still run expiry:
            # * the default 1s misfire window would silently drop that day's
            # * run (same defect class as the scheduled-unban fix, which uses
            # * 3600s). One coalesced late run per missed day is the correct
            # * daily semantics; 24h covers extended outages.
            misfire_grace_time=86400,
            coalesce=True,
        )
        log.info("Scheduled warn expiry: every 24h, expiry_days=%d.", warn_expiry_days)
    else:
        # * Warn expiry disabled: remove stale schedule if previously active.
        try:
            scheduler.remove_job(_WARN_EXPIRY_SCHEDULE_ID)
            log.info("Warn expiry schedule removed (WARN_EXPIRY_DAYS=0).")
        except Exception as exc:
            log.debug("Warn expiry schedule not present, skipping removal: %s", exc)

    # * member_cache cleanup is now handled by a MongoDB TTL index on last_updated.
    # * Remove the legacy weekly schedule if it was persisted from a prior bot version.
    try:
        scheduler.remove_job(_CLEANUP_SCHEDULE_ID)
        log.info("Removed legacy weekly cleanup schedule (now handled by TTL index).")
    except Exception as exc:
        log.debug("Legacy cleanup schedule not present, nothing to remove: %s", exc)

    if sync_interval_hours > 0 and _sync_bot is not None:
        scheduler.add_job(
            _run_scheduled_sync,
            trigger=IntervalTrigger(hours=sync_interval_hours),
            id=_SYNC_SCHEDULE_ID,
            replace_existing=True,
            # * Same misfire reasoning as warn expiry: a restart straddling
            # * the fire must still run the sweep once instead of dropping it.
            misfire_grace_time=86400,
            coalesce=True,
        )
        log.info("Scheduled enforcement sync: every %dh.", sync_interval_hours)
    else:
        # * Sync sweep disabled (or no bot reference): remove a stale schedule
        # * left by a previous enabled run so nothing fires without a bot.
        try:
            scheduler.remove_job(_SYNC_SCHEDULE_ID)
            log.info("Enforcement sync schedule removed (disabled).")
        except Exception as exc:
            log.debug("Sync schedule not present, skipping removal: %s", exc)


# ══════════════════════════════════════════════════════════════════ #
#  Lifecycle helpers
# ══════════════════════════════════════════════════════════════════ #


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
    global _sched_task, _sched_ready, _sched_stop, _sched_error, _sync_bot
    # * A live task means start() already ran: a second start would orphan
    # * the first scheduler and duplicate every job. Refuse loudly.
    if _sched_task is not None and not _sched_task.done():
        raise RuntimeError("APScheduler already started.")
    _sched_ready = asyncio.Event()
    _sched_stop = asyncio.Event()
    _sched_error = None
    _sync_bot = bot
    _sched_task = asyncio.create_task(
        _scheduler_background(
            mongodb_uri, db_name, warn_expiry_days, sync_interval_hours
        ),
        name="tcbot.scheduler",
    )
    try:
        await asyncio.wait_for(_sched_ready.wait(), timeout=_STOP_TIMEOUT_S)
    except asyncio.CancelledError:
        # * Shutdown raced startup: cancel the background task, wait for it
        # * to unwind, clear the globals, then propagate so the next start()
        # * sees clean state instead of a leaked half-started scheduler.
        if _sched_task is not None and not _sched_task.done():
            _sched_task.cancel()
            await asyncio.gather(_sched_task, return_exceptions=True)
        _sched_task = None
        _sched_ready = None
        _sched_stop = None
        _sched_error = None
        raise
    except TimeoutError:
        # * The background task did not signal readiness within the grace
        # * window (constructor raise before the try, or a hung jobstore
        # * handshake). Treat this like a startup failure so the caller
        # * fails fast instead of hanging at boot forever.
        _sched_error = TimeoutError(
            f"APScheduler did not become ready within {_STOP_TIMEOUT_S:.0f}s."
        )
        if _sched_task is not None and not _sched_task.done():
            _sched_task.cancel()
    if _sched_error is not None:
        startup_error = _sched_error
        if _sched_task is not None:
            await asyncio.gather(_sched_task, return_exceptions=True)
        _sched_task = None
        _sched_ready = None
        _sched_stop = None
        _sched_error = None
        raise RuntimeError("APScheduler failed to start.") from startup_error
    log.info("APScheduler ready (MongoDBJobStore → %s).", db_name)


async def stop() -> None:
    """Stop the scheduler and release all resources.

    Sets the stop event so the background task can exit cleanly.
    Safe to call even if :func:`start` was never called.
    """
    global _sched_task, _sched_ready, _sched_stop, _sched_error, _sync_bot
    if _sched_stop is not None:
        _sched_stop.set()
    if _sched_task is not None:
        try:
            await asyncio.wait_for(_sched_task, timeout=_STOP_TIMEOUT_S)
        except TimeoutError:
            log.warning(
                "APScheduler background task did not stop within %.0fs.",
                _STOP_TIMEOUT_S,
            )
            # * A stuck task left running would own a second live scheduler
            # * next start(): cancel it so shutdown never orphans execution.
            # * wait_for already gave up awaiting; cancel only signals.
            if not _sched_task.done():
                _sched_task.cancel()
                # * Best-effort unwind so task exceptions are retrieved and
                # * the next start() does not race a dying task. Bounded:
                # * a task that ignores cancellation is left to the loop.
                try:
                    await asyncio.wait_for(
                        asyncio.gather(_sched_task, return_exceptions=True),
                        timeout=2.0,
                    )
                except TimeoutError:
                    log.warning("APScheduler stuck task ignored cancellation.")
    _sched_task = None
    _sched_ready = None
    _sched_stop = None
    _sched_error = None
    _sync_bot = None
    log.info("APScheduler stopped.")


def is_ready() -> bool:
    """Return True only after scheduler startup has completed successfully."""
    return (
        _scheduler is not None
        and _sched_ready is not None
        and _sched_ready.is_set()
        and _sched_error is None
    )
