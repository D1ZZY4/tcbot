# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Scheduler job functions: warn expiry, legacy cleanup shim, and sync sweep."""

from __future__ import annotations

import asyncio
from datetime import timedelta

from tcbot.database import scheduler as _sched_pkg
from tcbot.database.mongos import col as _col
from tcbot.database.mongos import db_call as _db_call
from tcbot.utils.dispatch import throw_if_cancelled
from tcbot.utils.logger import get_logger
from tcbot.utils.time_and_date import utc_now

# * Logger keeps the pre-split name so log output is unchanged.
log = get_logger("tcbot.database.scheduler")

# * Ceiling for one warn-expiry delete batch: a hung MongoDB must fail the
# * run loudly instead of wedging the scheduler worker forever.
_EXPIRE_OP_TIMEOUT_S: float = 60.0
# * Ceiling for one scheduled enforcement sweep: a hung sync must end and
# * let the next interval re-drive instead of wedging the job.
_SYNC_RUN_TIMEOUT_S: float = 300.0


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

    bot = _sched_pkg._sync_bot
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
        "Scheduled enforcement sync: checked=%d enforced=%d remuted=%d skipped=%d failed=%d truncated=%s.",
        counts.checked,
        counts.enforced_bans,
        counts.enforced_mutes,
        counts.skipped,
        counts.failed,
        counts.truncated,
    )
