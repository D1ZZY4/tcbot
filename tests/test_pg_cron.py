# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Optional pg_cron ownership and the APScheduler hand-off."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from tcbot.database import pg_cron
from tcbot.database import scheduler as sched


def test_disabled_pg_cron_keeps_apscheduler_in_charge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    removed: list[bool] = []
    monkeypatch.setattr(
        pg_cron, "cfg", SimpleNamespace(pg_cron_enabled=False, db_schema="public")
    )

    async def _remove() -> None:
        removed.append(True)

    monkeypatch.setattr(pg_cron, "_remove_known_jobs", _remove)

    assert asyncio.run(pg_cron.sync_schedules()) is False
    assert removed == [True]


def test_missing_extension_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        pg_cron, "cfg", SimpleNamespace(pg_cron_enabled=True, db_schema="public")
    )

    async def _missing() -> bool:
        return False

    monkeypatch.setattr(pg_cron, "_extension_available", _missing)

    assert asyncio.run(pg_cron.sync_schedules()) is False


def test_every_registry_job_is_registered(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        pg_cron, "cfg", SimpleNamespace(pg_cron_enabled=True, db_schema="public")
    )
    scheduled: list[tuple[str, str, str]] = []

    async def _available() -> bool:
        return True

    async def _schedule(name: str, schedule: str, command: str) -> bool:
        scheduled.append((name, schedule, command))
        return True

    monkeypatch.setattr(pg_cron, "_extension_available", _available)
    monkeypatch.setattr(pg_cron, "_schedule_job", _schedule)

    assert asyncio.run(pg_cron.sync_schedules()) is True
    assert [job[0] for job in scheduled] == [
        "moderation.expire",
        "role.expire",
        "enforcement.reconcile",
        "scheduler.drift",
    ]
    assert "expire_due_moderation_actions_and_queue_revokes" in scheduled[0][2]
    assert "expire_due_role_assignments_and_audit" in scheduled[1][2]
    assert "reconcile_stuck_enforcement_targets" in scheduled[2][2]
    assert "run_scheduled_job" in scheduled[3][2]
    assert all('"public".' in job[2] for job in scheduled)


def test_partial_registration_rolls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        pg_cron, "cfg", SimpleNamespace(pg_cron_enabled=True, db_schema="public")
    )
    removed: list[str] = []

    async def _available() -> bool:
        return True

    async def _schedule(name: str, schedule: str, command: str) -> bool:
        return name != "role.expire"

    async def _remove(name: str) -> None:
        removed.append(name)

    monkeypatch.setattr(pg_cron, "_extension_available", _available)
    monkeypatch.setattr(pg_cron, "_schedule_job", _schedule)
    monkeypatch.setattr(pg_cron, "_remove_job", _remove)

    assert asyncio.run(pg_cron.sync_schedules()) is False
    assert removed == ["moderation.expire"]


def test_apscheduler_drops_the_expiry_job_when_pg_cron_owns_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensured: list[str] = []
    removed: list[str] = []

    def _ensure(*args: Any, **kwargs: Any) -> None:
        ensured.append(kwargs["job_id"])

    def _remove(*args: Any) -> None:
        removed.append(args[1])

    monkeypatch.setattr(sched, "_ensure_job", _ensure)
    monkeypatch.setattr(sched, "_remove_job", _remove)

    sched._reconcile_schedules(
        SimpleNamespace(),  # type: ignore[arg-type]
        SimpleNamespace(),  # type: ignore[arg-type]
        database_jobs_in_pg_cron=True,
    )

    assert "tcbot.expiry_daily" in removed
    assert "tcbot.expiry_daily" not in ensured
    assert "tcbot.stale_cleanup_daily" in ensured
