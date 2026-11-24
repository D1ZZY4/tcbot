# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Persistent moderation scheduler: APScheduler lifecycle and schedule catalog.

The maintenance jobs live in :mod:`tcbot.database.scheduler.jobs` so the
job implementations stay separate from the scheduling machinery. Every
name the package exposed before the split is re-exported here, including
the job functions: a persisted APScheduler record still references
``tcbot.database.scheduler.<name>`` and must keep resolving.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import contextlib
import functools
from datetime import UTC
from typing import TYPE_CHECKING, Any

from apscheduler.job import Job
from apscheduler.jobstores.base import BaseJobStore, JobLookupError
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import create_engine

from tcbot import cfg
from tcbot.database.connection_options import normalize_database_url, schema_options
from tcbot.database.scheduler.jobs import (
    _EXPIRE_OP_TIMEOUT_S,
    _cleanup_old_records,
    expire_due_decisions,
    expire_old_warns,
    expire_promotion_requests,
    expire_stale_records,
    process_erasure_queue,
    sweep_retention,
)
from tcbot.utils.logger import get_logger

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from datetime import tzinfo

    AsyncJob = Callable[[], Awaitable[None]]

log = get_logger(__name__)

# * Dotted import paths persisted in the job store (for example
# * ``tcbot.database.scheduler.expire_old_warns``) keep resolving because the
# * package re-exports every job function.
_scheduler: AsyncIOScheduler | None = None
_sched_task: asyncio.Task[None] | None = None
_sched_ready: asyncio.Event | None = None
_sched_stop: asyncio.Event | None = None
_sched_error: BaseException | None = None

# * Maximum seconds to wait for the scheduler background task to exit cleanly
# * before declaring it stuck. Ten seconds is the bot's shutdown grace window.
_STOP_TIMEOUT_S: float = 10.0

# * Maximum seconds to wait for the scheduler to become ready. The job store
# * reaches PostgreSQL over the network, so a slow or cold pooler (a remote
# * Supabase instance answers a checkout in roughly half a second) must not
# * turn an otherwise healthy boot into a crash loop. The work itself is
# * bounded by the job-store pool timeouts, so this is a safety net rather
# * than the normal path.
_STARTUP_TIMEOUT_S: float = 30.0

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


# ──────────────────────────── Schedules ──────────────────────────── #

# ──────────────── Recurring job schedule IDs ──────────────────── #
# * Stable IDs prevent duplicate schedules across restarts.
# * (replace_existing=True updates the trigger without creating duplicates)

_EXPIRY_SCHEDULE_ID: str = "tcbot.expiry_daily"
_PROMOTION_EXPIRY_SCHEDULE_ID: str = "tcbot.promotion_expiry_hourly"
_ENFORCEMENT_WORKER_SCHEDULE_ID: str = "tcbot.enforcement_worker"
_NOTIFICATION_WORKER_SCHEDULE_ID: str = "tcbot.notification_worker"
_ERASURE_SCHEDULE_ID: str = "tcbot.erasure_every_10m"
_RETENTION_SCHEDULE_ID: str = "tcbot.retention_daily"
# * ID of the retired warn-expiry job. It patched the warnings that had no
# * deadline, which the community schema forbids. The schedule is removed
# * on every startup so it cannot fire; the id stays here so the removal
# * keeps working on a job store written by an older version.
_LEGACY_WARN_EXPIRY_SCHEDULE_ID: str = "tcbot.warn_expiry_daily"
# * ID of the live stale-record cleanup job.
_CLEANUP_SCHEDULE_ID: str = "tcbot.stale_cleanup_daily"
# * ID of the retired weekly membership-cache cleanup job. The schedule is
# * removed on every startup so it cannot fire; the id stays here so the
# * removal keeps working on a job store written by an older version.
_LEGACY_CLEANUP_SCHEDULE_ID: str = "tcbot.db_cleanup_weekly"
# * ID of the retired enforcement-sweep job. The sweep it drove was
# * removed with the /tcsync command, so the schedule is removed on every
# * startup as well.
_LEGACY_SYNC_SCHEDULE_ID: str = "tcbot.enforcement_sync"

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

    ``SQLAlchemyJobStore.start()`` does two things: it binds the store
    to its scheduler, and it creates the job table with a blocking
    ``CREATE TABLE`` and a catalog read. The scheduler starts on the event
    loop, so that DDL would stall the loop for the whole connect timeout
    while the database is unreachable. The table is created on the worker
    thread instead, and this subclass makes the library's own creation
    call a no-op.

    The binding is kept: a job that is read back from the store carries
    the scheduler, and the scheduler is what turns the next run time of
    a due job into a real date. Without it, every job that is overdue
    when the bot starts raises inside the scheduler, its next run time
    is never written back, and the job fires again on every tick.
    """

    def start(self, scheduler: Any, alias: str) -> None:
        """Bind the store to its scheduler without running the library's DDL."""
        BaseJobStore.start(self, scheduler, alias)


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
        normalize_database_url(database_url),
        pool_size=_JOBSTORE_POOL_SIZE,
        max_overflow=0,
        pool_timeout=_JOBSTORE_POOL_TIMEOUT_S,
        pool_pre_ping=True,
        connect_args={
            "connect_timeout": _JOBSTORE_CONNECT_TIMEOUT_S,
            # * The job table belongs to the same schema as the rest of the
            # * application. Without the search path a deployment that names
            # * a schema would create and read the table in ``public``.
            "options": schema_options(cfg.db_schema, primary_chat_id=cfg.main_group),
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
    *,
    database_jobs_in_pg_cron: bool,
    enforcement_job: AsyncJob | None,
    notification_job: AsyncJob | None,
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
    scheduler: AsyncIOScheduler | None = None
    started = False
    try:
        store = await loop.run_in_executor(
            _scheduler_pool(),
            _build_job_store,
            database_url,
        )
        # * The loop is bound explicitly so the scheduler can be started from
        # * a worker thread: APScheduler would otherwise call
        # * get_running_loop() there and fail.
        scheduler = AsyncIOScheduler(
            event_loop=asyncio.get_running_loop(),
            jobstores={_JOBSTORE_ALIAS: store},
            timezone=_SCHEDULER_TIMEZONE,
        )
        _scheduler = scheduler
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
        # * the database is unreachable, freezing every handler with it.
        await loop.run_in_executor(
            _scheduler_pool(),
            functools.partial(
                _reconcile_schedules,
                scheduler,
                store,
                database_jobs_in_pg_cron=database_jobs_in_pg_cron,
                enforcement_job=enforcement_job,
                notification_job=notification_job,
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
        if started and scheduler is not None:
            with contextlib.suppress(Exception):
                scheduler.shutdown(wait=False)
        _scheduler = None
        log.info("APScheduler background task exited.")


def _schedule_matches(
    job: Job, func: Callable[..., Any], trigger: IntervalTrigger, args: tuple[Any, ...]
) -> bool:
    """Return True when the stored job already runs the desired schedule.

    Only the interval, the timezone, and the arguments are compared: an
    ``IntervalTrigger`` derives its ``start_date`` from the current clock, so
    two triggers built a second apart are never equal even when they describe
    the same cadence. The timezone is part of the comparison so a job
    persisted against the host-local zone is replaced once the schedules run
    on UTC. The callable is compared as well: a stored job that points at an
    older implementation at the same cadence must be replaced, or a code fix
    would never run.
    """
    stored_trigger = job.trigger
    if not isinstance(stored_trigger, IntervalTrigger):
        return False
    if stored_trigger.timezone != trigger.timezone:
        return False
    stored_func = getattr(job, "func", None)
    if stored_func is not func and stored_func != func:
        return False
    return stored_trigger.interval == trigger.interval and tuple(job.args) == args


def _stored_jobs(store: SQLAlchemyJobStore) -> dict[str, Job] | None:
    """Return every persisted job once, keyed by id.

    The schedule reconciliation used to issue one ``lookup_job`` and one
    ``remove_job`` per known schedule. Every job-store call checks a
    connection out of a remote pool, and a pooled PostgreSQL checkout costs
    a round trip of its own, so nine separate calls pushed a healthy boot
    past the readiness window. One bulk read replaces all of them; ``None``
    means the read failed and the caller falls back to replacing every
    schedule.
    """
    try:
        return {job.id: job for job in store.get_all_jobs()}
    except Exception as exc:
        log.warning(
            "Stored schedule read failed (%s); every schedule is replaced.", exc
        )
        return None


def _ensure_job(
    scheduler: AsyncIOScheduler,
    *,
    job_id: str,
    func: Callable[..., Any],
    trigger: IntervalTrigger,
    args: tuple[Any, ...],
    misfire_grace_time: int,
    stored: dict[str, Job] | None,
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
    existing = stored.get(job_id) if stored is not None else None
    if existing is not None:
        try:
            matches = _schedule_matches(existing, func, trigger, args)
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


def _remove_job(
    scheduler: AsyncIOScheduler,
    job_id: str,
    label: str,
    *,
    stored: dict[str, Job] | None,
) -> None:
    """Remove a persisted job from the job store.

    The store is addressed directly: ``scheduler.remove_job`` only reaches
    the stores while the scheduler is running, so a removal issued before
    ``start()`` would silently do nothing and leave a stale schedule firing.
    A job the bulk read already proved absent skips the delete entirely.
    """
    if stored is not None and job_id not in stored:
        log.debug("%s schedule not present, nothing to remove.", label)
        return
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
    *,
    database_jobs_in_pg_cron: bool,
    enforcement_job: AsyncJob | None = None,
    notification_job: AsyncJob | None = None,
) -> None:
    """Align the persisted schedules with the current configuration.

    The stored schedules are read once. Each entry is compared in memory,
    and a job that already runs the desired cadence costs no database
    round trip at all.
    """
    stored = _stored_jobs(store)
    # * The expiry sweep always runs somewhere. pg_cron owns it when the
    # * extension is active, so APScheduler must not run a second copy.
    if database_jobs_in_pg_cron:
        _remove_job(
            scheduler,
            _EXPIRY_SCHEDULE_ID,
            "Expiry sweep (pg_cron)",
            stored=stored,
        )
    else:
        _ensure_job(
            scheduler,
            job_id=_EXPIRY_SCHEDULE_ID,
            func=expire_due_decisions,
            trigger=IntervalTrigger(hours=24, timezone=_SCHEDULER_TIMEZONE),
            args=(),
            misfire_grace_time=86400,
            stored=stored,
        )
        log.info("Scheduled expiry sweep: every 24h.")

    # * The retired warn-expiry job patched the warnings that had no
    # * deadline. The community schema treats the expiry of a decision as
    # * a fact of it, so the schedule is removed instead of replaced.
    _remove_job(
        scheduler,
        _LEGACY_WARN_EXPIRY_SCHEDULE_ID,
        "Warn expiry",
        stored=stored,
    )

    # * PostgreSQL has no TTL index, so the daily cleanup job replaces the
    # * one the MongoDB TTL index used to provide.
    _ensure_job(
        scheduler,
        job_id=_CLEANUP_SCHEDULE_ID,
        func=expire_stale_records,
        trigger=IntervalTrigger(hours=24, timezone=_SCHEDULER_TIMEZONE),
        args=(),
        misfire_grace_time=86400,
        stored=stored,
    )
    log.info("Scheduled stale record cleanup: every 24h.")

    # * The registry owns the retention contract of every table. Without a
    # * caller the telemetry policies stayed unapplied and those tables grew
    # * without bound. The sweep records itself in ``scheduled_job_runs``.
    _ensure_job(
        scheduler,
        job_id=_RETENTION_SCHEDULE_ID,
        func=sweep_retention,
        trigger=IntervalTrigger(hours=24, timezone=_SCHEDULER_TIMEZONE),
        args=(),
        misfire_grace_time=86400,
        stored=stored,
    )
    log.info("Scheduled retention sweep: every 24h.")

    # * A promotion request that nobody decides must release its target
    # * for a fresh request. The sweep is idempotent and lazy reads cover
    # * the gap while the scheduler is down.
    _ensure_job(
        scheduler,
        job_id=_PROMOTION_EXPIRY_SCHEDULE_ID,
        func=expire_promotion_requests,
        trigger=IntervalTrigger(hours=1, timezone=_SCHEDULER_TIMEZONE),
        args=(),
        misfire_grace_time=3600,
        stored=stored,
    )
    log.info("Scheduled promotion request expiry: every hour.")

    # * The registry registers ``user.erasure`` as a ten-minute
    # * application job. The daily cleanup also drains the queue, but an
    # * operator-queued deletion must not wait for the maintenance window.
    _ensure_job(
        scheduler,
        job_id=_ERASURE_SCHEDULE_ID,
        func=process_erasure_queue,
        trigger=IntervalTrigger(minutes=10, timezone=_SCHEDULER_TIMEZONE),
        args=(),
        misfire_grace_time=600,
        stored=stored,
    )
    log.info("Scheduled erasure queue: every 10 minutes.")

    # * The expiry sweep only queues the per-group revokes. The application
    # * passes the worker entry points in, so the storage layer never imports
    # * the Telegram delivery modules. The callables still have stable module
    # * paths, so APScheduler persists and reloads them by reference.
    if enforcement_job is not None:
        _ensure_job(
            scheduler,
            job_id=_ENFORCEMENT_WORKER_SCHEDULE_ID,
            func=enforcement_job,
            trigger=IntervalTrigger(minutes=5, timezone=_SCHEDULER_TIMEZONE),
            args=(),
            misfire_grace_time=300,
            stored=stored,
        )
        log.info("Scheduled enforcement worker: every 5 minutes.")
    else:
        # * No callable supplied: a job persisted by an earlier boot must not
        # * keep firing by its stored reference after the owner opted out.
        _remove_job(
            scheduler,
            _ENFORCEMENT_WORKER_SCHEDULE_ID,
            "Enforcement worker",
            stored=stored,
        )

    # * A review-card edit that failed in the handler is retried here, so
    # * a settled appeal cannot leave a live-looking card behind.
    if notification_job is not None:
        _ensure_job(
            scheduler,
            job_id=_NOTIFICATION_WORKER_SCHEDULE_ID,
            func=notification_job,
            trigger=IntervalTrigger(minutes=5, timezone=_SCHEDULER_TIMEZONE),
            args=(),
            misfire_grace_time=300,
            stored=stored,
        )
        log.info("Scheduled notification worker: every 5 minutes.")
    else:
        _remove_job(
            scheduler,
            _NOTIFICATION_WORKER_SCHEDULE_ID,
            "Notification worker",
            stored=stored,
        )

    # * The retired weekly cleanup job must not fire: it pointed at a
    # * membership sweep the daily job replaced.
    _remove_job(
        scheduler,
        _LEGACY_CLEANUP_SCHEDULE_ID,
        "Legacy DB cleanup",
        stored=stored,
    )

    # * The retired enforcement-sweep job must not fire either: the sweep
    # * it drove no longer exists.
    _remove_job(
        scheduler,
        _LEGACY_SYNC_SCHEDULE_ID,
        "Enforcement sync",
        stored=stored,
    )


# ──────────────────────────── Lifecycle ──────────────────────────── #


async def start(
    database_url: str,
    *,
    database_jobs_in_pg_cron: bool = False,
    enforcement_job: AsyncJob | None = None,
    notification_job: AsyncJob | None = None,
) -> None:
    """Initialise and start the APScheduler background scheduler.

    Spawns a dedicated asyncio task that calls ``scheduler.start()`` inside
    the running event loop. Uses ``SQLAlchemyJobStore`` so all schedules and
    job state survive bot restarts. ``database_jobs_in_pg_cron`` removes the
    pure-database expiry schedule when pg_cron already owns it.

    Blocks until the scheduler is ready to accept schedule operations.

    Args:
        database_url: PostgreSQL connection string (same as ``DATABASE_URL``).
        database_jobs_in_pg_cron: Remove the pure-database expiry schedule
            when pg_cron already owns it.
        enforcement_job: The application's enforcement worker entry point.
            The storage layer never imports it, so the dependency points
            from the runtime into the scheduler.
        notification_job: The application's review-card retry worker.

    """
    global _sched_ready, _sched_stop, _sched_error, _sched_task
    # * A live task means start() already ran: a second start would orphan
    # * the first scheduler and duplicate every job. Refuse loudly.
    if _sched_task is not None and not _sched_task.done():
        raise RuntimeError("APScheduler already started.")
    _sched_ready = asyncio.Event()
    _sched_stop = asyncio.Event()
    _sched_error = None
    _sched_task = asyncio.create_task(
        _scheduler_background(
            database_url,
            database_jobs_in_pg_cron=database_jobs_in_pg_cron,
            enforcement_job=enforcement_job,
            notification_job=notification_job,
        ),
        name="tcbot.scheduler",
    )
    try:
        await asyncio.wait_for(_sched_ready.wait(), timeout=_STARTUP_TIMEOUT_S)
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
        # * window. A construction or reconcile failure now reports itself
        # * immediately through ``_sched_error``, so this branch covers a
        # * hung jobstore handshake. Cancel it and unwind bounded so a task
        # * ignoring cancellation cannot hang start beyond the outer bound.
        _sched_error = TimeoutError(
            f"APScheduler did not become ready within {_STARTUP_TIMEOUT_S:.0f}s."
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
    global _sched_task, _sched_ready, _sched_stop, _sched_error
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
    log.info("APScheduler stopped.")


def is_ready() -> bool:
    """Return True only after scheduler startup has completed successfully."""
    return (
        _scheduler is not None
        and _sched_ready is not None
        and _sched_ready.is_set()
        and _sched_error is None
    )


__all__ = [
    "_EXPIRE_OP_TIMEOUT_S",
    "_cleanup_old_records",
    "expire_due_decisions",
    "expire_old_warns",
    "expire_promotion_requests",
    "expire_stale_records",
    "is_ready",
    "process_erasure_queue",
    "start",
    "stop",
    "sweep_retention",
]
