# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""APScheduler background task and periodic schedule registration."""

from __future__ import annotations

import contextlib

from apscheduler.jobstores.mongodb import MongoDBJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from tcbot.database import scheduler as _sched_pkg
from tcbot.database.mongos import (
    mongo_client_kwargs as _mongo_client_kwargs,
)
from tcbot.database.mongos import (
    mongo_jobstore_kwargs as _mongo_jobstore_kwargs,
)
from tcbot.utils.logger import get_logger

from .jobs import _run_scheduled_sync, expire_old_warns

# * Logger keeps the pre-split name so log output is unchanged.
log = get_logger("tcbot.database.scheduler")

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
    _sched_pkg._scheduler = scheduler
    started = False
    try:
        _register_periodic_schedules(
            scheduler, warn_expiry_days, sync_interval_hours=sync_interval_hours
        )
        scheduler.start()
        started = True
        if _sched_pkg._sched_ready is None:
            raise RuntimeError(
                "_sched_ready event not initialised before _scheduler_background ran"
            )
        if _sched_pkg._sched_stop is None:
            raise RuntimeError(
                "_sched_stop event not initialised before _scheduler_background ran"
            )
        # Signal readiness only after the recurring schedules are registered
        # and the scheduler has accepted background execution.
        _sched_pkg._sched_ready.set()
        await _sched_pkg._sched_stop.wait()
        scheduler.shutdown(wait=False)
        started = False
    except Exception as exc:
        log.exception("APScheduler background task crashed.")
        _sched_pkg._sched_error = exc
        if _sched_pkg._sched_ready is not None and not _sched_pkg._sched_ready.is_set():
            _sched_pkg._sched_ready.set()  # unblock start() so it doesn't hang forever
    finally:
        # * A crash or cancellation past start() must still release the
        # * scheduler and its synchronous MongoClient; otherwise the
        # * process leaks both while reporting itself stopped.
        if started:
            with contextlib.suppress(Exception):
                scheduler.shutdown(wait=False)
        _sched_pkg._scheduler = None
        log.info("APScheduler background task exited.")


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

    if sync_interval_hours > 0 and _sched_pkg._sync_bot is not None:
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
