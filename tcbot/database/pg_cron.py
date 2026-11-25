# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Optional pg_cron ownership of the pure-database maintenance jobs.

pg_cron runs inside PostgreSQL, so the expiry and role-assignment sweeps
keep running when no bot process is alive, and the scheduler-drift audit
runs where it can read ``cron.job``. The feature is opt-in because the
extension is not available on every hosted PostgreSQL plan. When it is
disabled or unavailable the caller keeps the APScheduler schedules.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import text

from tcbot import cfg
from tcbot.database.engine import db_call, fetch_value, run
from tcbot.database.migrations import _SCHEMA_PATTERN
from tcbot.utils.logger import get_logger

if TYPE_CHECKING:
    from collections.abc import Sequence

log = get_logger(__name__)

# * Job names match the ``scheduled_jobs`` registry keys, so the existing
# * drift report can compare the registry with ``cron.job`` without a
# * translation table.
_MODERATION_EXPIRE_JOB: str = "moderation.expire"
_ROLE_EXPIRE_JOB: str = "role.expire"
_ENFORCEMENT_RECONCILE_JOB: str = "enforcement.reconcile"
_SCHEDULER_DRIFT_JOB: str = "scheduler.drift"

# * The CRON expressions come from the registry seed.
_MODERATION_EXPIRE_SCHEDULE: str = "*/5 * * * *"
_ROLE_EXPIRE_SCHEDULE: str = "*/10 * * * *"
_ENFORCEMENT_RECONCILE_SCHEDULE: str = "*/5 * * * *"
_SCHEDULER_DRIFT_SCHEDULE: str = "*/15 * * * *"


def _qualified(function_name: str) -> str:
    """Return the schema-qualified name of one SQL function."""
    schema = cfg.db_schema
    if not _SCHEMA_PATTERN.fullmatch(schema):
        raise ValueError(
            f"Refusing to build pg_cron command for invalid schema {schema!r}"
        )
    return f'"{schema}".{function_name}'


def _jobs() -> tuple[tuple[str, str, str], ...]:
    """Return the (job name, schedule, command) tuples pg_cron owns."""
    return (
        (
            _MODERATION_EXPIRE_JOB,
            _MODERATION_EXPIRE_SCHEDULE,
            f"SELECT {_qualified('run_scheduled_job')}('{_MODERATION_EXPIRE_JOB}');",
        ),
        (
            _ROLE_EXPIRE_JOB,
            _ROLE_EXPIRE_SCHEDULE,
            f"SELECT {_qualified('run_scheduled_job')}('{_ROLE_EXPIRE_JOB}');",
        ),
        (
            _ENFORCEMENT_RECONCILE_JOB,
            _ENFORCEMENT_RECONCILE_SCHEDULE,
            f"SELECT {_qualified('run_scheduled_job')}('{_ENFORCEMENT_RECONCILE_JOB}');",
        ),
        (
            _SCHEDULER_DRIFT_JOB,
            _SCHEDULER_DRIFT_SCHEDULE,
            f"SELECT {_qualified('run_scheduled_job')}('scheduler.drift');",
        ),
    )


async def _extension_available() -> bool:
    """Return True when the connected database has the pg_cron extension."""
    try:
        value = await db_call(
            lambda: fetch_value(
                text(
                    "SELECT EXISTS ("
                    "SELECT 1 FROM pg_extension WHERE extname = 'pg_cron'"
                    ")"
                )
            )
        )
    except Exception as exc:
        log.debug("pg_cron extension check failed: %s", exc)
        return False
    return bool(value)


async def _remove_job(name: str) -> None:
    """Remove one pg_cron job; a missing job is not an error."""
    try:
        await db_call(
            lambda: run(text("SELECT cron.unschedule(:name)").bindparams(name=name))
        )
    except Exception as exc:
        log.debug("pg_cron job %s was not removed: %s", name, exc)


async def _remove_known_jobs() -> None:
    """Remove the jobs this module owns.

    This is the single-owner sweep, so it must run even when the extension
    check fails: that is precisely the case where a previous boot may have
    left registrations behind. ``_remove_job`` already treats an absent
    extension or a missing job as a benign debug-level outcome.
    """
    for name, _schedule, _command in _jobs():
        await _remove_job(name)


async def _schedule_job(name: str, schedule: str, command: str) -> bool:
    """Replace one pg_cron job; return False when the registration failed."""
    await _remove_job(name)
    try:
        await db_call(
            lambda: run(
                text("SELECT cron.schedule(:name, :schedule, :command)").bindparams(
                    name=name, schedule=schedule, command=command
                )
            )
        )
    except Exception:
        log.exception("pg_cron job %s could not be scheduled", name)
        return False
    return True


async def sync_schedules() -> bool:
    """Register the database maintenance jobs when pg_cron owns them.

    Returns True only when the extension is present and every job was
    registered. On a partial failure every job this module owns is removed,
    including entries left by an earlier boot, so a failed hand-off cannot
    leave pg_cron and APScheduler running the same sweep concurrently.
    """
    if not cfg.pg_cron_enabled:
        # * Honour a toggle-off: remove jobs a previous deployment created.
        await _remove_known_jobs()
        return False
    if not await _extension_available():
        log.warning(
            "PG_CRON_ENABLED is set but the database has no pg_cron "
            "extension; keeping the APScheduler schedules."
        )
        # * An extension check can fail after a boot that did register the
        # * jobs. Without this sweep that earlier registration keeps firing
        # * alongside APScheduler, breaking the single-owner guarantee.
        await _remove_known_jobs()
        return False

    scheduled: list[str] = []
    for name, schedule, command in _jobs():
        if not await _schedule_job(name, schedule, command):
            # * The failing slot removed its old entry before trying. Sweep
            # * all known names so an entry created by an earlier boot cannot
            # * survive a hand-off that fell back to APScheduler.
            await _remove_known_jobs()
            return False
        scheduled.append(name)
    log.info(
        "pg_cron owns %d database maintenance job(s): %s",
        len(scheduled),
        ", ".join(scheduled),
    )
    return True


__all__: Sequence[str] = ("sync_schedules",)
