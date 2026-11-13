# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Scheduler job-store wiring: persistence, idempotent schedules, and fail-fast startup."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from apscheduler.jobstores.base import BaseJobStore, JobLookupError

from tcbot.database import scheduler as sched_mod

# * The URL is never dialled: the job store is replaced by a double.
_TEST_URL: str = "postgresql://tcbot@127.0.0.1:1/tcbot_placeholder"


class _FakeJobStore(BaseJobStore):
    """In-memory stand-in for the PostgreSQL job store."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__()
        self.kwargs = kwargs
        self.jobs: dict[str, Any] = {}
        self.started = False
        self.removed: list[str] = []

    def start(self, scheduler: Any, alias: str) -> None:
        super().start(scheduler, alias)
        self.started = True

    def lookup_job(self, job_id: str) -> Any:
        return self.jobs.get(job_id)

    def get_due_jobs(self, now: Any) -> list[Any]:  # type: ignore[override]
        return []

    def get_next_run_time(self) -> None:
        return None

    def get_all_jobs(self) -> list[Any]:  # type: ignore[override]
        return list(self.jobs.values())

    def add_job(self, job: Any) -> None:
        self.jobs[job.id] = job

    def update_job(self, job: Any) -> None:
        self.jobs[job.id] = job

    def remove_job(self, job_id: str) -> None:
        if job_id not in self.jobs:
            raise JobLookupError(job_id)
        del self.jobs[job_id]
        self.removed.append(job_id)

    def remove_all_jobs(self) -> None:
        self.jobs.clear()

    def shutdown(self) -> None:
        return None


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> _FakeJobStore:
    """Install a job-store double that survives every scheduler boot."""
    created = _FakeJobStore()
    monkeypatch.setattr(sched_mod, "_build_job_store", lambda _url: created)
    return created


@pytest.fixture(autouse=True)
def _reset_scheduler() -> None:
    """Reset module state between tests so no live task crosses asyncio loops."""
    if sched_mod._sched_task is None:
        return
    asyncio.run(sched_mod.stop())


def _run_scheduler() -> None:
    """Start and stop the scheduler once with a job-store double installed."""

    async def _run() -> None:
        await sched_mod.start(_TEST_URL)
        await sched_mod.stop()

    asyncio.run(_run())


def test_schedules_land_in_the_persistent_job_store(store: _FakeJobStore) -> None:
    """Jobs must not fall back to APScheduler's in-memory default store."""
    _run_scheduler()

    assert store.started is True
    assert sched_mod._EXPIRY_SCHEDULE_ID in store.jobs
    job = store.jobs[sched_mod._EXPIRY_SCHEDULE_ID]
    assert job.args == ()
    assert job.coalesce is True
    assert job.misfire_grace_time == 86400


def test_unchanged_schedule_keeps_its_persisted_fire_time(
    store: _FakeJobStore,
) -> None:
    """A restart must not reset the daily cadence of an unchanged schedule."""
    _run_scheduler()
    persisted_next_run = store.jobs[sched_mod._EXPIRY_SCHEDULE_ID].next_run_time

    _run_scheduler()

    assert store.jobs[sched_mod._EXPIRY_SCHEDULE_ID].next_run_time == persisted_next_run


def test_the_retired_warn_expiry_schedule_is_not_registered(
    store: _FakeJobStore,
) -> None:
    """The old warn-expiry job must not fire next to the expiry sweep."""
    _run_scheduler()

    assert sched_mod._LEGACY_WARN_EXPIRY_SCHEDULE_ID not in store.jobs


def test_a_corrupt_stored_schedule_is_replaced(store: _FakeJobStore) -> None:
    """A stored job the code cannot compare must not fail the boot.

    A job row left behind by an older schema version can carry a shape
    this code cannot read. Replacing it is safe, so the schedule is
    rewritten instead of the scheduler refusing to start.
    """
    store.jobs[sched_mod._CLEANUP_SCHEDULE_ID] = object()

    _run_scheduler()

    replaced = store.jobs[sched_mod._CLEANUP_SCHEDULE_ID]
    assert replaced is not object()
    assert replaced.args == ()


def test_startup_failure_is_reported_on_the_module_global(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A scheduler that cannot start must fail the boot, not log and continue."""
    monkeypatch.setattr(sched_mod, "_STOP_TIMEOUT_S", 2.0)

    def _boom(_url: str) -> _FakeJobStore:
        raise RuntimeError("jobstore handshake failed")

    monkeypatch.setattr(sched_mod, "_build_job_store", _boom)

    with pytest.raises(RuntimeError, match="APScheduler failed to start"):
        _run_scheduler()


def test_startup_failure_does_not_leave_a_live_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed start must clear the task handle so the next start is clean."""
    monkeypatch.setattr(sched_mod, "_STOP_TIMEOUT_S", 2.0)

    def _boom(_url: str) -> _FakeJobStore:
        raise RuntimeError("jobstore handshake failed")

    monkeypatch.setattr(sched_mod, "_build_job_store", _boom)

    with pytest.raises(RuntimeError):
        _run_scheduler()
    assert sched_mod._sched_task is None
    assert sched_mod.is_ready() is False
