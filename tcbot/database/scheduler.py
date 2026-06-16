# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Studio

"""Persistent moderation scheduler backed by APScheduler 4.x + MongoDB.

All scheduled moderation actions (warn expiry) survive bot restarts
because APScheduler stores its schedule state in MongoDB via MongoDBDataStore.
Member-cache cleanup is handled by a MongoDB TTL index on ``last_updated``,
not by a scheduler job.

The scheduler runs inside a dedicated asyncio background task so that the
``async with AsyncScheduler()`` context manager is entered *and* exited in the
same task (AnyIO cancel-scope semantics requires this).

Usage pattern (lifecycle managed by ``tcbot/__main__.py``)::

    await scheduler.start(mongodb_uri, db_name, warn_expiry_days)
    # ... bot runs ...
    await scheduler.stop()

Scheduling a one-off action::

    schedule_id = await scheduler.schedule_unban(ban_id, user_id, run_at)
    # cancel if user manually unbanned before expiry:
    await scheduler.cancel_schedule(schedule_id)
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

from apscheduler import AsyncScheduler, ConflictPolicy
from apscheduler.datastores.mongodb import MongoDBDataStore
from apscheduler.serializers.cbor import CBORSerializer
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

# * Direct module imports (not through tcbot.database.__init__) to avoid circular
# * imports: tcbot.database.__init__ → scheduler → tcbot.database.__init__
from tcbot.database.bans_db import deactivate_ban as _bans_deactivate
from tcbot.database.mongos import col as _col
from tcbot.utils.timedate_format import utc_now

log = logging.getLogger(__name__)

# ──────────────── Recurring job schedule IDs ──────────────────── #
# * Stable IDs prevent duplicate schedules across restarts.
# * (conflict_policy=replace updates the trigger without creating duplicates)

_WARN_EXPIRY_SCHEDULE_ID: str = "tcbot.warn_expiry_daily"
# * Legacy ID kept so _register_periodic_schedules can remove the old schedule
# * from any MongoDB datastore that was created before the TTL-index migration.
_CLEANUP_SCHEDULE_ID: str = "tcbot.db_cleanup_weekly"

# ──────────────── Module-level scheduler state ──────────────────── #
# * _scheduler:   live AsyncScheduler reference (set inside background task)
# * _sched_task:  the asyncio Task that keeps async-with context alive
# * _sched_ready: event set when the scheduler is initialised and available
# * _sched_stop:  event set by stop() to trigger graceful shutdown

_scheduler: AsyncScheduler | None = None
_sched_task: asyncio.Task | None = None  # type: ignore[type-arg]
_sched_ready: asyncio.Event | None = None
_sched_stop: asyncio.Event | None = None


# ══════════════════════════════════════════════════════════════════ #
#  Persistent job functions
#  Must be module-level callables so APScheduler can serialise their
#  import paths into MongoDB and call them after bot restarts.
# ══════════════════════════════════════════════════════════════════ #


async def _expire_old_warns(warn_expiry_days: int) -> None:
    """Delete warn_count records whose ``updated_at`` is older than *warn_expiry_days* days.

    Called daily by APScheduler when ``WARN_EXPIRY_DAYS > 0``.
    """
    cutoff = utc_now() - timedelta(days=warn_expiry_days)
    result = await _col("warn_counts").delete_many({"updated_at": {"$lt": cutoff}})
    log.info(
        "Warn expiry: removed %d warn_count records older than %d days.",
        result.deleted_count,
        warn_expiry_days,
    )


async def _cleanup_old_records() -> None:
    """No-op migration shim for the retired weekly member_cache cleanup job.

    member_cache cleanup is now handled automatically by the MongoDB TTL index on
    ``last_updated`` (``expireAfterSeconds=7776000``, equivalent to 90 days), added
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


async def _execute_scheduled_unban(ban_id: str, user_id: int) -> None:
    """Deactivate a timed ban record in MongoDB when its scheduled expiry fires.

    NOTE: This only updates the DB record (``is_active = False``). The actual
    Telegram unban is handled by the timed ``restrict_chat_member`` call with
    ``until_date`` at ban time, which Telegram enforces natively.
    """
    deactivated = await _bans_deactivate(ban_id)
    if deactivated:
        log.info(
            "Scheduled unban: deactivated ban_id=%s for user_id=%d.", ban_id, user_id
        )
    else:
        log.debug(
            "Scheduled unban: ban_id=%s not found or already inactive (user_id=%d).",
            ban_id,
            user_id,
        )


# ══════════════════════════════════════════════════════════════════ #
#  Background task: keeps async-with context alive
# ══════════════════════════════════════════════════════════════════ #


async def _scheduler_background(
    mongodb_uri: str, db_name: str, warn_expiry_days: int
) -> None:
    """Long-running background task that owns the AsyncScheduler context.

    AnyIO requires that the cancel scope created by ``async with AsyncScheduler()``
    is entered and exited in the *same* asyncio task.  Running this entire
    lifecycle inside a dedicated task satisfies that requirement.
    """
    global _scheduler
    serializer = CBORSerializer()
    data_store = MongoDBDataStore(mongodb_uri, database=db_name, serializer=serializer)
    try:
        async with AsyncScheduler(data_store) as sched:
            _scheduler = sched
            if _sched_ready is None:
                raise RuntimeError("_sched_ready event not initialised before _scheduler_background ran")
            _sched_ready.set()
            await _register_periodic_schedules(sched, warn_expiry_days)
            await sched.start_in_background()
            if _sched_stop is None:
                raise RuntimeError("_sched_stop event not initialised before _scheduler_background ran")
            await _sched_stop.wait()
    except Exception:
        log.exception("APScheduler background task crashed.")
        if _sched_ready is not None and not _sched_ready.is_set():
            _sched_ready.set()  # unblock start() so it doesn't hang forever
    finally:
        _scheduler = None
        log.info("APScheduler background task exited.")


# ══════════════════════════════════════════════════════════════════ #
#  Periodic schedule registration (takes sched as explicit param)
# ══════════════════════════════════════════════════════════════════ #


async def _register_periodic_schedules(
    sched: AsyncScheduler, warn_expiry_days: int
) -> None:
    """Register recurring maintenance schedules (idempotent via ConflictPolicy.replace)."""
    if warn_expiry_days > 0:
        await sched.add_schedule(
            _expire_old_warns,
            IntervalTrigger(hours=24),
            id=_WARN_EXPIRY_SCHEDULE_ID,
            kwargs={"warn_expiry_days": warn_expiry_days},
            conflict_policy=ConflictPolicy.replace,
        )
        log.info("Scheduled warn expiry: every 24h, expiry_days=%d.", warn_expiry_days)
    else:
        # * Warn expiry disabled: remove stale schedule if previously active.
        try:
            await sched.remove_schedule(_WARN_EXPIRY_SCHEDULE_ID)
            log.info("Warn expiry schedule removed (WARN_EXPIRY_DAYS=0).")
        except Exception as exc:
            log.debug("Warn expiry schedule not present, skipping removal: %s", exc)

    # * member_cache cleanup is now handled by a MongoDB TTL index on last_updated.
    # * Remove the legacy weekly schedule if it was persisted from a prior bot version.
    try:
        await sched.remove_schedule(_CLEANUP_SCHEDULE_ID)
        log.info("Removed legacy weekly cleanup schedule (now handled by TTL index).")
    except Exception as exc:
        log.debug("Legacy cleanup schedule not present, nothing to remove: %s", exc)


# ══════════════════════════════════════════════════════════════════ #
#  Lifecycle helpers
# ══════════════════════════════════════════════════════════════════ #


async def start(mongodb_uri: str, db_name: str, warn_expiry_days: int) -> None:
    """Initialise and start the APScheduler background scheduler.

    Spawns a dedicated asyncio task that owns the ``async with AsyncScheduler()``
    context (required by AnyIO cancel-scope semantics).  Uses ``MongoDBDataStore``
    with ``CBORSerializer`` so all schedules and job state survive bot restarts.

    Blocks until the scheduler is ready to accept schedule operations.

    Args:
        mongodb_uri: MongoDB connection string (same as ``MONGODB_URI``).
        db_name: MongoDB database name (same as ``DB_NAME``).
        warn_expiry_days: Days after which warn_counts are expired (0 = disabled).

    """
    global _sched_task, _sched_ready, _sched_stop
    _sched_ready = asyncio.Event()
    _sched_stop = asyncio.Event()
    _sched_task = asyncio.create_task(
        _scheduler_background(mongodb_uri, db_name, warn_expiry_days),
        name="tcbot.scheduler",
    )
    await _sched_ready.wait()
    log.info("APScheduler ready (MongoDBDataStore + CBORSerializer → %s).", db_name)


async def stop() -> None:
    """Stop the scheduler and release all resources.

    Sets the stop event so the background task can exit the ``async with`` block
    cleanly.  Safe to call even if :func:`start` was never called.
    """
    global _sched_task, _sched_ready, _sched_stop
    if _sched_stop is not None:
        _sched_stop.set()
    if _sched_task is not None:
        try:
            await asyncio.wait_for(_sched_task, timeout=10.0)
        except TimeoutError:
            log.warning("APScheduler background task did not stop within 10s.")
    _sched_task = None
    _sched_ready = None
    _sched_stop = None
    log.info("APScheduler stopped.")


def _get() -> AsyncScheduler:
    """Return the active scheduler; raises if not started."""
    if _scheduler is None:
        raise RuntimeError("Scheduler not started; call start() first.")
    return _scheduler


def is_ready() -> bool:
    """Return True when the scheduler background task is running and ready."""
    return _scheduler is not None


# ══════════════════════════════════════════════════════════════════ #
#  Public scheduling helpers
# ══════════════════════════════════════════════════════════════════ #


async def schedule_unban(ban_id: str, user_id: int, run_at: datetime) -> str:
    """Schedule a persistent DB-side unban at *run_at* (UTC).

    Returns the APScheduler schedule ID which can be passed to
    :func:`cancel_schedule` if the user is manually unbanned before expiry.

    The schedule is stored in MongoDB so it survives bot restarts.
    """
    schedule_id = f"unban.{ban_id}"
    await _get().add_schedule(
        _execute_scheduled_unban,
        DateTrigger(run_at),
        id=schedule_id,
        kwargs={"ban_id": ban_id, "user_id": user_id},
        conflict_policy=ConflictPolicy.replace,
    )
    log.info(
        "Scheduled persistent unban: ban_id=%s user_id=%d run_at=%s.",
        ban_id,
        user_id,
        run_at.isoformat(),
    )
    return schedule_id


async def cancel_schedule(schedule_id: str) -> bool:
    """Cancel a persistent schedule by ID. Returns True if it existed.

    Safe to call with a non-existent ID (returns False, does not raise).
    """
    try:
        await _get().remove_schedule(schedule_id)
        log.info("Cancelled schedule: %s.", schedule_id)
        return True
    except Exception:
        log.debug(
            "cancel_schedule: %s not found (already fired or never created).",
            schedule_id,
        )
        return False


async def run_now(
    func: object,
    *,
    args: tuple | None = None,
    kwargs: dict | None = None,
) -> None:
    """Queue *func* for immediate one-shot execution via the scheduler.

    Useful for triggering a job on demand (e.g. admin-triggered action).
    """
    await _get().add_schedule(
        func,
        DateTrigger(utc_now()),
        args=args or (),
        kwargs=kwargs or {},
        conflict_policy=ConflictPolicy.replace,
    )
