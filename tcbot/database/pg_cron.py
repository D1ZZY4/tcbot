# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Optional pg_cron ownership of the pure-database maintenance jobs.

pg_cron runs inside PostgreSQL, so the expiry and role-assignment sweeps
keep running when no bot process is alive. The feature is opt-in because
the extension is not available on every hosted PostgreSQL plan. When it is
disabled or unavailable the caller keeps the APScheduler schedules.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import text

from tcbot import cfg
from tcbot.database.engine import db_call, fetch_value, run
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

# * The CRON expressions come from the registry seed.
_MODERATION_EXPIRE_SCHEDULE: str = "*/5 * * * *"
_ROLE_EXPIRE_SCHEDULE: str = "*/10 * * * *"
_ENFORCEMENT_RECONCILE_SCHEDULE: str = "*/5 * * * *"


def _qualified(function_name: str) -> str:
    """Return the schema-qualified name of one SQL function."""
    return f'"{cfg.db_schema}".{function_name}'


def _jobs() -> tuple[tuple[str, str, str], ...]:
    """Return the (job name, schedule, command) tuples pg_cron owns."""
    return (
        (
            _MODERATION_EXPIRE_JOB,
            _MODERATION_EXPIRE_SCHEDULE,
            f"SELECT {_qualified('expire_due_moderation_actions_and_queue_revokes')}();",
        ),
        (
            _ROLE_EXPIRE_JOB,
            _ROLE_EXPIRE_SCHEDULE,
            f"SELECT {_qualified('expire_due_role_assignments_and_audit')}();",
        ),
        (
            _ENFORCEMENT_RECONCILE_JOB,
            _ENFORCEMENT_RECONCILE_SCHEDULE,
            f"SELECT {_qualified('reconcile_stuck_enforcement_targets')}();",
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
    """Remove the jobs this module owns, when the extension is present."""
    if not await _extension_available():
        return
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
    registered. On a partial failure the jobs registered by this call are
    removed again, so the caller can safely keep APScheduler as the single
    owner instead of running some sweeps twice.
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
        return False

    scheduled: list[str] = []
    for name, schedule, command in _jobs():
        if not await _schedule_job(name, schedule, command):
            for registered in scheduled:
                await _remove_job(registered)
            return False
        scheduled.append(name)
    log.info(
        "pg_cron owns %d database maintenance job(s): %s",
        len(scheduled),
        ", ".join(scheduled),
    )
    return True


__all__: Sequence[str] = ("sync_schedules",)
