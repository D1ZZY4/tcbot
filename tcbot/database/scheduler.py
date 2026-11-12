# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Persistent moderation scheduler backed by APScheduler 3.x + PostgreSQL."""

from __future__ import annotations

import asyncio
import concurrent.futures
import contextlib
import functools
from datetime import UTC, timedelta
from typing import TYPE_CHECKING, Any, cast

from apscheduler.job import Job
from apscheduler.jobstores.base import JobLookupError
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import create_engine, delete

from tcbot.database.base import active_mutes, member_cache, warn_counts, warns
from tcbot.database.engine import db_call as _db_call
from tcbot.database.engine import run as _run
from tcbot.database.engine import run_transaction
from tcbot.utils.dispatch import throw_if_cancelled
from tcbot.utils.logger import get_logger
from tcbot.utils.time_and_date import utc_now

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import tzinfo

    from sqlalchemy.engine import CursorResult
    from sqlalchemy.ext.asyncio import AsyncSession
    from telegram import Bot

log = get_logger(__name__)

# * Dotted import paths persisted in the job store (for example
# * ``tcbot.database.scheduler.expire_old_warns``) keep resolving because the
# * functions live in this single module.
_scheduler: AsyncIOScheduler | None = None
_sched_task: asyncio.Task[None] | None = None
_sched_ready: asyncio.Event | None = None
_sched_stop: asyncio.Event | None = None
_sched_error: BaseException | None = None
_sync_bot: Bot | None = None
# * Enforcement runner supplied by the runtime lifecycle (which already imports
# * the command modules). Keeping the callable here avoids the
# * database -> modules import cycle: this module never imports a command
# * module; the lifecycle injects the runner at startup.
_sync_runner: Callable[..., Any] | None = None

# * Maximum seconds to wait for the scheduler background task to exit cleanly
# * before declaring it stuck.  10 s matches the PTB shutdown grace window.
_STOP_TIMEOUT_S: float = 10.0

# * Dedicated worker for the blocking job-store calls. The event loop's
# * default executor is shared with other blocking work, and a speed test
# * holds one of its threads for the whole measurement, so the scheduler
# * must not queue behind it.
_scheduler_executor: concurrent.futures.ThreadPoolExecutor | None = None


def _scheduler_pool() -> concurrent.futures.ThreadPoolExecutor:
    """Return the dedicated scheduler worker, creating it on first use."""
    global _scheduler_executor
    if _scheduler_executor is None:
        _scheduler_executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="tcbot-scheduler"
        )
    return _scheduler_executor


# ────────────────────────────── Jobs ────────────────────────────── #

# * Ceiling for one warn-expiry delete batch: a hung database must fail the
# * run loudly instead of wedging the scheduler worker forever.
_EXPIRE_OP_TIMEOUT_S: float = 60.0
# * Ceiling for one scheduled enforcement sweep: a hung sync must end and
# * let the next interval re-drive instead of wedging the job.
_SYNC_RUN_TIMEOUT_S: float = 300.0
# * How long a cached profile is kept before the daily cleanup drops it.
# * It replaces the TTL pruning the MongoDB deployment did on its own.
_MEMBER_CACHE_EXPIRE_DAYS: int = 90


async def expire_old_warns(warn_expiry_days: int) -> None:
    """Delete expired warn records from both ``warns`` and ``warn_counts``.

    Both tables must be pruned together. Deleting only ``warn_counts``
    leaves individual ``warns`` rows intact; ``_sync_warn_count`` then
    reconstructs the counter from those rows on the next warn operation,
    making expiry a no-op. Deleting only ``warns`` leaves the counter
    behind, and the counter is what the auto-ban threshold reads: the
    user would keep a phantom warning with an empty history.

    The two deletes therefore share one transaction. Separate statements
    would each commit on their own, so a failure between them could leave
    exactly the half-pruned state the pair is meant to prevent. A
    transaction commits both deletes or neither.

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

    async def _work(sess: AsyncSession) -> tuple[int, int]:
        counts_result = await sess.execute(
            delete(warn_counts).where(warn_counts.c.updated_at < cutoff)
        )
        warns_result = await sess.execute(
            delete(warns).where(warns.c.timestamp < cutoff)
        )
        # * A write returns a cursor result, which carries the affected row
        # * count. The generic result type does not expose it.
        return (
            cast("CursorResult", counts_result).rowcount,
            cast("CursorResult", warns_result).rowcount,
        )

    try:
        # * The budget belongs to the transaction itself: the run-level
        # * timeout would otherwise fire first and report a shorter
        # * deadline than the one the operator is told about.
        counts_del, warns_del = await run_transaction(
            _work,
            timeout=_EXPIRE_OP_TIMEOUT_S,
        )
    except TimeoutError:
        log.exception(
            "Warn expiry timed out after %ds; no expiry completed.",
            _EXPIRE_OP_TIMEOUT_S,
        )
        # * A hung expiry must fail the run, not report success: returning
        # * normally would make the serverless cron endpoint answer 200
        # * while warns were never pruned.
        raise RuntimeError(
            "Warn expiry timed out: no records expired; see errors above."
        ) from None
    except Exception as exc:
        # * The transaction rolled back, so the two tables still agree.
        # * Surface the failure: the caller must not read the partial
        # * state as a completed expiry.
        log.exception("Warn expiry failed; the prune was rolled back.")
        raise RuntimeError(
            "Warn expiry incomplete: the prune was rolled back; see errors above."
        ) from exc
    log.info(
        "Warn expiry: removed %d warn_count and %d warn records older than %d days.",
        counts_del,
        warns_del,
        warn_expiry_days,
    )


async def expire_stale_records() -> None:
    """Delete the rows PostgreSQL cannot expire on its own.

    The MongoDB deployment pruned two tables on its own: the timed
    federation mutes whose deadline passed, and the cached profiles that
    were not refreshed for 90 days. PostgreSQL has no TTL index, so the
    same pruning runs here, once a day.

    A timed mute row is only enforcement state: the query that reads it
    already filters the expired rows out, so a late cleanup changes
    nothing but the storage. The member cache rows keep the user
    listings and the name search accurate, so they must be pruned or the
    table grows without bound.

    Called daily by APScheduler, and on demand by the serverless cron
    endpoint (``api/cron.py``) which cannot run a persistent scheduler.
    """
    now = utc_now()
    profile_cutoff = now - timedelta(days=_MEMBER_CACHE_EXPIRE_DAYS)
    try:
        async with asyncio.timeout(_EXPIRE_OP_TIMEOUT_S):
            mutes_res, profiles_res = await asyncio.gather(
                _db_call(
                    lambda: _run(
                        delete(active_mutes).where(
                            active_mutes.c.until_date.isnot(None),
                            active_mutes.c.until_date < now,
                        )
                    ),
                    # * Bulk deletes over the whole table may run long;
                    # * the run-level timeout bounds them instead.
                    timeout=None,
                ),
                _db_call(
                    lambda: _run(
                        delete(member_cache).where(
                            member_cache.c.last_updated < profile_cutoff
                        )
                    ),
                    timeout=None,
                ),
                return_exceptions=True,
            )
    except TimeoutError:
        log.exception(
            "Stale record cleanup timed out after %ds; no cleanup completed.",
            _EXPIRE_OP_TIMEOUT_S,
        )
        raise RuntimeError(
            "Stale record cleanup timed out: nothing expired; see errors above."
        ) from None
    # ! CRITICAL: a cancelled cleanup must propagate, not report success.
    throw_if_cancelled((mutes_res, profiles_res))
    failures = [r for r in (mutes_res, profiles_res) if isinstance(r, BaseException)]
    if failures:
        for failure in failures:
            log.error("Stale record cleanup failed: %s", failure)
        raise RuntimeError(
            "Stale record cleanup incomplete; see errors above."
        ) from failures[0]
    log.info(
        "Stale record cleanup: removed %d expired mute rows and %d stale profiles.",
        mutes_res,
        profiles_res,
    )


async def _cleanup_old_records() -> None:
    """No-op migration shim for the retired weekly member_cache cleanup job.

    member_cache cleanup is now handled by the daily :func:`expire_stale_records`
    job, because PostgreSQL has no TTL index.  The APScheduler schedule is
    removed on startup in ``_reconcile_schedules``; this function exists solely
    so that any schedule record persisted from a previous bot version can be
    deserialised and called without raising an ``AttributeError``.  It is safe
    to remove once all running instances have been restarted and the job store
    no longer contains the ``tcbot.db_cleanup_weekly`` schedule entry.
    """
    log.info(
        "DB cleanup job called but is now a no-op; "
        "cleanup is handled by the daily expire_stale_records job."
    )


async def _run_scheduled_sync() -> None:
    """Run one bounded enforcement sweep (the ``/tcsync`` core on a timer).

    Module-level so APScheduler can serialise its import path into the job store.
    Results go to the log only: there is no operator message to edit here.
    A missing bot (or any failure) logs and returns; the next interval
    re-drives, so one bad run never wedges the schedule.
    """
    bot = _sync_bot
    runner = _sync_runner
    if bot is None or runner is None:
        log.debug("Scheduled sync skipped: no bot reference.")
        return
    try:
        async with asyncio.timeout(_SYNC_RUN_TIMEOUT_S):
            counts = await runner(bot)
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


# ──────────────────────────── Schedules ──────────────────────────── #

# ──────────────── Recurring job schedule IDs ──────────────────── #
# * Stable IDs prevent duplicate schedules across restarts.
# * (replace_existing=True updates the trigger without creating duplicates)

_WARN_EXPIRY_SCHEDULE_ID: str = "tcbot.warn_expiry_daily"
# * Stable ID for the optional enforcement-sync sweep (/tcsync core on a
# * timer). Same replace_existing idempotency as the warn-expiry schedule.
_SYNC_SCHEDULE_ID: str = "tcbot.enforcement_sync"
# * Legacy ID kept so _reconcile_schedules can remove the old schedule
# * from any job store that was created before the cleanup job replaced it.
_CLEANUP_SCHEDULE_ID: str = "tcbot.db_cleanup_weekly"

# * Alias of the persistent job store. Every job must name it explicitly:
# * APScheduler defaults to the ``default`` alias, which is auto-created as an
# * in-memory store, so a job registered without it never reaches the database
# * and dies with the process.
_JOBSTORE_ALIAS: str = "postgres"
# * The table the scheduler owns. APScheduler creates it on first use, so
# * the application migrations do not have to mirror the library schema.
_JOBSTORE_TABLE: str = "apscheduler_jobs"
# * The job store's own pool and timeouts. They are deliberately smaller
# * than the main client's: the store is single-threaded and it runs on
# * the event loop, where a long stall freezes the whole bot.
_JOBSTORE_POOL_SIZE: int = 2
_JOBSTORE_POOL_TIMEOUT_S: float = 5.0
_JOBSTORE_CONNECT_TIMEOUT_S: int = 2

# * The schedules run on UTC. APScheduler defaults to the host's local zone,
# * which is both unpicklable when the zone came from a file stream (the
# * job store pickles the trigger, so the bot would refuse to boot)
# * and host-dependent, so the daily expiry would fire at a different local
# * midnight on every machine.
_SCHEDULER_TIMEZONE: tzinfo = UTC


class _PreparedJobStore(SQLAlchemyJobStore):
    """Job store whose table already exists when the scheduler starts.

    ``SQLAlchemyJobStore.start()`` creates the job table with a blocking
    ``CREATE TABLE`` and a catalog read. The scheduler starts on the event
    loop, so that DDL would stall the loop for the whole connect timeout
    while the database is unreachable. The table is created on the worker
    thread instead, and this subclass makes the library's own creation
    call a no-op.
    """

    def start(self, scheduler: Any, alias: str) -> None:
        """Skip the library's table creation; it already happened."""


def _build_job_store(database_url: str) -> SQLAlchemyJobStore:
    """Build the persistent PostgreSQL job store.

    Runs on a worker thread: the constructor creates a synchronous
    SQLAlchemy engine, which resolves the host of the connection string
    inside the constructor and would otherwise block the event loop. The
    job table is created here too, so the scheduler never runs DDL on the
    event loop.

    The store reads and writes on the event loop, so its client uses
    short timeouts and a two-connection pool: a database outage must
    stall the bot for seconds, not for the timeout of the main client,
    and the store never needs more than the two connections its
    single-threaded use can occupy.
    """
    engine = create_engine(
        database_url,
        pool_size=_JOBSTORE_POOL_SIZE,
        max_overflow=0,
        pool_timeout=_JOBSTORE_POOL_TIMEOUT_S,
        pool_pre_ping=True,
        connect_args={
            "connect_timeout": _JOBSTORE_CONNECT_TIMEOUT_S,
            "options": "-c timezone=UTC",
        },
    )
    store = _PreparedJobStore(engine=engine, tablename=_JOBSTORE_TABLE)
    # * The table creation is the library's own schema, so it is created
    # * here rather than in start(): the statement is idempotent and the
    # * check keeps the store usable on a database that already has it.
    store.jobs_t.create(store.engine, checkfirst=True)
    return store


async def _scheduler_background(
    database_url: str,
    warn_expiry_days: int,
    sync_interval_hours: int = 0,
) -> None:
    """Long-running background task that owns the AsyncIOScheduler lifecycle.

    Starts the scheduler, reconciles the persisted schedules, then waits for
    the stop event before shutting the scheduler down.
    """
    global _scheduler, _sched_error
    # * The job store builds its own synchronous engine, so it needs the
    # * same TLS trust as the main client: without the certifi bundle an
    # * Atlas handshake fails with CERTIFICATE_VERIFY_FAILED on sandboxes
    # * whose system CA store is stale.
    # * The constructor also performs the blocking DNS lookup, so it runs
    # * on a worker thread instead of stalling the event loop.
    loop = asyncio.get_running_loop()
    store = await loop.run_in_executor(
        _scheduler_pool(),
        _build_job_store,
        database_url,
    )
    # * The loop is bound explicitly so the scheduler can be started from a
    # * worker thread: APScheduler would otherwise call get_running_loop()
    # * there and fail.
    scheduler = AsyncIOScheduler(
        event_loop=asyncio.get_running_loop(),
        jobstores={_JOBSTORE_ALIAS: store},
        timezone=_SCHEDULER_TIMEZONE,
    )
    _scheduler = scheduler
    started = False
    try:
        # * The scheduler starts on the event loop: it arms its own timer
        # * with loop.call_later, which is not thread-safe. Starting it on
        # * a worker thread would mutate the loop's timer heap while the
        # * loop is popping from it. The job table was already created on
        # * the worker thread, so start() touches no database.
        scheduler.start()
        started = True
        # * The job store performs blocking database calls (table creation,
        # * job insert/update/lookup) and every one of them would otherwise
        # * stall the event loop for the whole server-selection timeout while
        # * the database is unreachable, freezing the webhook receiver with it.
        await loop.run_in_executor(
            _scheduler_pool(),
            functools.partial(
                _reconcile_schedules,
                scheduler,
                store,
                warn_expiry_days,
                sync_interval_hours=sync_interval_hours,
            ),
        )
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
        # * Module-level global: a local assignment here would leave the
        # * startup check reading a stale None and the bot would boot with a
        # * dead scheduler and a "ready" log line.
        _sched_error = exc
        if _sched_ready is not None and not _sched_ready.is_set():
            _sched_ready.set()  # unblock start() so it doesn't hang forever
    finally:
        # * A crash or cancellation past start() must still release the
        # * scheduler and its synchronous engine; otherwise the process
        # * leaks both while reporting itself stopped.
        if started:
            with contextlib.suppress(Exception):
                scheduler.shutdown(wait=False)
        _scheduler = None
        log.info("APScheduler background task exited.")


def _schedule_matches(
    job: Job, trigger: IntervalTrigger, args: tuple[Any, ...]
) -> bool:
    """Return True when the stored job already runs the desired schedule.

    Only the interval, the timezone, and the arguments are compared: an
    ``IntervalTrigger`` derives its ``start_date`` from the current clock, so
    two triggers built a second apart are never equal even when they describe
    the same cadence. The timezone is part of the comparison so a job
    persisted against the host-local zone is replaced once the schedules run
    on UTC.
    """
    stored_trigger = job.trigger
    if not isinstance(stored_trigger, IntervalTrigger):
        return False
    if stored_trigger.timezone != trigger.timezone:
        return False
    return stored_trigger.interval == trigger.interval and tuple(job.args) == args


def _ensure_job(
    scheduler: AsyncIOScheduler,
    store: SQLAlchemyJobStore,
    *,
    job_id: str,
    func: Callable[..., Any],
    trigger: IntervalTrigger,
    args: tuple[Any, ...],
    misfire_grace_time: int,
) -> None:
    """Register a recurring job without resetting an unchanged schedule.

    ``add_job(replace_existing=True)`` always rewrites ``next_run_time`` from
    the current clock. Re-adding the job at every boot would therefore reset
    the daily cadence on each restart, and a bot that restarts more often
    than the interval would never let the job fire. The stored job is left
    untouched when its interval and arguments still match, so the persisted
    fire time, the misfire grace window, and the coalescing behaviour survive
    a restart.
    """
    try:
        existing = store.lookup_job(job_id)
    except Exception as exc:
        log.warning("Job lookup failed for %s: %s", job_id, exc)
        existing = None
    if existing is not None:
        try:
            matches = _schedule_matches(existing, trigger, args)
        except Exception as exc:
            # * A stored job from an older schema version can carry a
            # * shape this code cannot compare. Replacing it is safe, so
            # * the schedule is rewritten instead of failing the boot.
            log.warning(
                "Stored schedule %s could not be compared (%s); replacing it.",
                job_id,
                exc,
            )
            matches = False
        if matches:
            log.info("Schedule %s kept (next run %s).", job_id, existing.next_run_time)
            return
    scheduler.add_job(
        func,
        trigger=trigger,
        id=job_id,
        args=list(args),
        jobstore=_JOBSTORE_ALIAS,
        replace_existing=True,
        # * A restart straddling the daily fire must still run expiry:
        # * the default 1s misfire window would silently drop that day's
        # * run (same defect class as the scheduled-unban fix, which uses
        # * 3600s). One coalesced late run per missed day is the correct
        # * daily semantics; 24h covers extended outages.
        misfire_grace_time=misfire_grace_time,
        coalesce=True,
    )


def _remove_job(scheduler: AsyncIOScheduler, job_id: str, label: str) -> None:
    """Remove a persisted job from the job store.

    The store is addressed directly: ``scheduler.remove_job`` only reaches
    the stores while the scheduler is running, so a removal issued before
    ``start()`` would silently do nothing and leave a stale schedule firing.
    """
    try:
        scheduler.remove_job(job_id, jobstore=_JOBSTORE_ALIAS)
        log.info("Removed %s schedule.", label)
    except JobLookupError:
        log.debug("%s schedule not present, nothing to remove.", label)
    except Exception as exc:
        log.warning(
            "%s schedule removal failed: a stale schedule may keep firing: %s",
            label,
            exc,
        )


def _reconcile_schedules(
    scheduler: AsyncIOScheduler,
    store: SQLAlchemyJobStore,
    warn_expiry_days: int,
    *,
    sync_interval_hours: int = 0,
) -> None:
    """Align the persisted schedules with the current configuration."""
    if warn_expiry_days > 0:
        _ensure_job(
            scheduler,
            store,
            job_id=_WARN_EXPIRY_SCHEDULE_ID,
            func=expire_old_warns,
            trigger=IntervalTrigger(hours=24, timezone=_SCHEDULER_TIMEZONE),
            args=(warn_expiry_days,),
            misfire_grace_time=86400,
        )
        log.info("Scheduled warn expiry: every 24h, expiry_days=%d.", warn_expiry_days)
    else:
        # * Warn expiry disabled: remove stale schedule if previously active.
        _remove_job(scheduler, _WARN_EXPIRY_SCHEDULE_ID, "Warn expiry")

    # * PostgreSQL has no TTL index, so the daily cleanup job replaces the
    # * one the MongoDB TTL index used to provide.
    _ensure_job(
        scheduler,
        store,
        job_id=_CLEANUP_SCHEDULE_ID,
        func=expire_stale_records,
        trigger=IntervalTrigger(hours=24, timezone=_SCHEDULER_TIMEZONE),
        args=(),
        misfire_grace_time=86400,
    )
    log.info("Scheduled stale record cleanup: every 24h.")

    if sync_interval_hours > 0 and _sync_bot is not None:
        _ensure_job(
            scheduler,
            store,
            job_id=_SYNC_SCHEDULE_ID,
            func=_run_scheduled_sync,
            trigger=IntervalTrigger(
                hours=sync_interval_hours, timezone=_SCHEDULER_TIMEZONE
            ),
            args=(),
            misfire_grace_time=86400,
        )
        log.info("Scheduled enforcement sync: every %dh.", sync_interval_hours)
    else:
        # * Sync sweep disabled (or no bot reference): remove a stale schedule
        # * left by a previous enabled run so nothing fires without a bot.
        _remove_job(scheduler, _SYNC_SCHEDULE_ID, "Enforcement sync")


# ──────────────────────────── Lifecycle ──────────────────────────── #


async def start(
    database_url: str,
    warn_expiry_days: int,
    *,
    bot: Bot | None = None,
    sync_interval_hours: int = 0,
    sync_runner: Callable[..., Any] | None = None,
) -> None:
    """Initialise and start the APScheduler background scheduler.

    Spawns a dedicated asyncio task that calls ``scheduler.start()`` inside the
    running event loop.  Uses ``SQLAlchemyJobStore`` so all schedules and job
    state survive bot restarts.

    Blocks until the scheduler is ready to accept schedule operations.

    Args:
        database_url: PostgreSQL connection string (same as ``DATABASE_URL``).
        warn_expiry_days: Days after which warn_counts are expired (0 = disabled).
        bot: Live bot for the optional enforcement-sync sweep (same as
            ``SYNC_INTERVAL_HOURS``); ``None`` disables the sweep.
        sync_interval_hours: Hours between enforcement sweeps (0 = disabled).
        sync_runner: Enforcement sweep supplied by the runtime lifecycle,
            which already imports the command modules. Passing it here
            keeps the database package free of a modules import while
            making the dependency explicit; ``None`` disables the sweep.

    """
    global _sched_ready, _sched_stop, _sched_error, _sync_bot, _sync_runner, _sched_task
    # * A live task means start() already ran: a second start would orphan
    # * the first scheduler and duplicate every job. Refuse loudly.
    if _sched_task is not None and not _sched_task.done():
        raise RuntimeError("APScheduler already started.")
    _sched_ready = asyncio.Event()
    _sched_stop = asyncio.Event()
    _sched_error = None
    _sync_bot = bot
    _sync_runner = sync_runner
    _sched_task = asyncio.create_task(
        _scheduler_background(database_url, warn_expiry_days, sync_interval_hours),
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
        # * handshake). Cancel it and unwind bounded so a task ignoring
        # * cancellation cannot hang start beyond the outer bound.
        _sched_error = TimeoutError(
            f"APScheduler did not become ready within {_STOP_TIMEOUT_S:.0f}s."
        )
        if _sched_task is not None and not _sched_task.done():
            _sched_task.cancel()
            try:
                await asyncio.wait_for(
                    asyncio.gather(_sched_task, return_exceptions=True),
                    timeout=2.0,
                )
            except TimeoutError:
                log.warning("APScheduler startup task ignored cancellation.")
    if _sched_error is not None:
        startup_error = _sched_error
        if _sched_task is not None:
            try:
                await asyncio.wait_for(
                    asyncio.gather(_sched_task, return_exceptions=True),
                    timeout=2.0,
                )
            except TimeoutError:
                log.warning("APScheduler startup task ignored cancellation.")
        _sched_task = None
        _sched_ready = None
        _sched_stop = None
        _sched_error = None
        raise RuntimeError("APScheduler failed to start.") from startup_error
    log.info("APScheduler ready (SQLAlchemyJobStore).")


async def stop() -> None:
    """Stop the scheduler and release all resources.

    Sets the stop event so the background task can exit cleanly.
    Safe to call even if :func:`start` was never called.
    """
    global _sched_task, _sched_ready, _sched_stop, _sched_error, _sync_bot, _sync_runner
    if _sched_stop is not None:
        _sched_stop.set()
    if _sched_task is not None:
        try:
            await asyncio.wait_for(_sched_task, timeout=_STOP_TIMEOUT_S)
        except asyncio.CancelledError:
            # * Cancellation of stop() itself must still clear the globals;
            # * gather retrieves the task exception so the next start() does
            # * not race a dying task, then propagate.
            if _sched_task is not None and not _sched_task.done():
                _sched_task.cancel()
                await asyncio.gather(_sched_task, return_exceptions=True)
            _sched_task = None
            _sched_ready = None
            _sched_stop = None
            _sched_error = None
            _sync_bot = None
            _sync_runner = None
            raise
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
        except Exception as exc:
            log.warning("APScheduler background task failed during stop: %s", exc)
    _sched_task = None
    _sched_ready = None
    _sched_stop = None
    _sched_error = None
    _sync_bot = None
    _sync_runner = None
    log.info("APScheduler stopped.")


def is_ready() -> bool:
    """Return True only after scheduler startup has completed successfully."""
    return (
        _scheduler is not None
        and _sched_ready is not None
        and _sched_ready.is_set()
        and _sched_error is None
    )
