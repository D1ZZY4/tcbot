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
    # * Every database job goes through the registry dispatcher, so a
    # * pg_cron-owned sweep records the same run and failure telemetry as the
    # * APScheduler-owned one.
    assert [job[2] for job in scheduled] == [
        "SELECT \"public\".run_scheduled_job('moderation.expire');",
        "SELECT \"public\".run_scheduled_job('role.expire');",
        "SELECT \"public\".run_scheduled_job('enforcement.reconcile');",
        "SELECT \"public\".run_scheduled_job('scheduler.drift');",
    ]


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
    # * A stale entry from an earlier boot must not keep running after the
    # * hand-off to APScheduler has failed.
    assert removed == [
        "moderation.expire",
        "role.expire",
        "enforcement.reconcile",
        "scheduler.drift",
    ]


def test_apscheduler_drops_the_expiry_job_when_pg_cron_owns_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensured: list[str] = []
    removed: list[str] = []

    def _ensure(*args: Any, **kwargs: Any) -> None:
        ensured.append(kwargs["job_id"])

    def _remove(*args: Any, **kwargs: Any) -> None:
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
