# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Scheduler startup: bounded readiness wait so a dead background task cannot hang boot."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from tcbot.database import scheduler as sched_mod


@pytest.fixture(autouse=True)
def _reset_scheduler() -> None:
    """Reset module state between tests so no live task crosses asyncio loops."""
    if sched_mod._sched_task is None:
        return
    asyncio.run(sched_mod.stop())


def test_start_raises_runtime_error_when_background_dies_before_try(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _boom(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(sched_mod, "_STOP_TIMEOUT_S", 0.1)
    monkeypatch.setattr(sched_mod, "_scheduler_background", _boom)

    with pytest.raises(RuntimeError, match="APScheduler failed to start"):
        asyncio.run(sched_mod.start("mongodb://x", "db", 0))


def test_start_raises_runtime_error_on_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _never_ready(*args: Any, **kwargs: Any) -> None:
        await asyncio.sleep(3600)

    monkeypatch.setattr(sched_mod, "_STOP_TIMEOUT_S", 0.1)
    monkeypatch.setattr(sched_mod, "_scheduler_background", _never_ready)

    with pytest.raises(RuntimeError, match="APScheduler failed to start"):
        # * Outer bound so a regression (unbounded ready wait) fails, not hangs.
        asyncio.run(asyncio.wait_for(sched_mod.start("mongodb://x", "db", 0), 1.0))
    # * Timeout unwind reaps the stuck task so no stop() is needed.
    assert sched_mod._sched_task is None


def test_start_success_path_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _ready(*args: Any, **kwargs: Any) -> None:
        if sched_mod._sched_ready is not None:
            sched_mod._sched_ready.set()

    monkeypatch.setattr(sched_mod, "_STOP_TIMEOUT_S", 0.1)
    monkeypatch.setattr(sched_mod, "_scheduler_background", _ready)

    asyncio.run(sched_mod.start("mongodb://x", "db", 0))
    asyncio.run(sched_mod.stop())
