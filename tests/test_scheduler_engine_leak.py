# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""A cancelled job-store build must not leak its synchronous engine."""

from __future__ import annotations

import asyncio
import concurrent.futures
import threading
from typing import Any

import pytest

from tcbot.database import scheduler as sched


class _FakeStore:
    def __init__(self) -> None:
        self.shutdowns = 0

    def shutdown(self) -> None:
        self.shutdowns += 1


@pytest.mark.asyncio
async def test_a_store_finishing_after_cancellation_is_disposed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The orphan future owns disposal when its awaiting task was cancelled."""
    entered = threading.Event()
    release = threading.Event()
    store = _FakeStore()

    def _slow_build(_url: str) -> Any:
        entered.set()
        release.wait(timeout=5)
        return store

    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    monkeypatch.setattr(sched, "_scheduler_pool", lambda: pool)
    monkeypatch.setattr(sched, "_build_job_store", _slow_build)
    monkeypatch.setattr(sched, "_sched_ready", asyncio.Event())
    monkeypatch.setattr(sched, "_sched_stop", asyncio.Event())

    task = asyncio.create_task(
        sched._scheduler_background(
            "postgresql://localhost/db",
            database_jobs_in_pg_cron=False,
            enforcement_job=None,
            notification_job=None,
        )
    )
    await asyncio.wait_for(asyncio.to_thread(entered.wait, timeout=5), timeout=6)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    release.set()
    await asyncio.to_thread(lambda: pool.shutdown(wait=True))
    await asyncio.sleep(0)

    assert store.shutdowns == 1


def test_a_failed_job_store_build_disposes_its_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A DDL failure must close the engine the caller never receives."""
    disposed: list[bool] = []

    class _Engine:
        def dispose(self) -> None:
            disposed.append(True)

    class _Table:
        def create(self, _engine: object, *, checkfirst: bool) -> None:
            raise RuntimeError("DDL refused")

    class _Store:
        def __init__(self, **_kwargs: Any) -> None:
            self.engine = _Engine()
            self.jobs_t = _Table()

    monkeypatch.setattr(sched, "create_engine", lambda *_a, **_k: _Engine())
    monkeypatch.setattr(sched, "_PreparedJobStore", _Store)

    with pytest.raises(RuntimeError, match="DDL refused"):
        sched._build_job_store("postgresql://localhost/db")

    assert disposed == [True]
