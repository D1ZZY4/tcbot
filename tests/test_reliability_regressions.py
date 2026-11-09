# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Reliability regressions: scheduler stop and member-cache bound."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from tcbot import __main__ as members
from tcbot.database import scheduler as sched_mod


@pytest.fixture(autouse=True)
def _reset_scheduler() -> None:
    if sched_mod._sched_task is None:
        return
    asyncio.run(sched_mod.stop())


def test_scheduler_stop_clears_state_on_task_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _boom() -> None:
        raise RuntimeError("task boom")

    monkeypatch.setattr(sched_mod, "_STOP_TIMEOUT_S", 1.0)

    async def _run() -> None:
        sched_mod._sched_stop = asyncio.Event()
        sched_mod._sched_ready = asyncio.Event()
        sched_mod._sched_ready.set()
        sched_mod._sched_error = None
        sched_mod._sync_bot = None
        sched_mod._sched_task = asyncio.create_task(_boom())
        await sched_mod.stop()
        assert sched_mod._sched_task is None
        assert sched_mod._sched_ready is None
        assert sched_mod._sched_stop is None
        assert sched_mod._sched_error is None
        assert sched_mod._sync_bot is None

    asyncio.run(_run())


def test_member_cache_skips_when_at_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    created: list[asyncio.Task[None]] = []

    async def _noop(uid: int, *args: Any, **kwargs: Any) -> None:
        return None

    monkeypatch.setattr("tcbot.database.users_cache.harvest_user_identity", _noop)
    members._member_cache_tasks.clear()

    # Fill to the cap with never-done tasks on a live loop.
    async def _scenario() -> None:
        for _ in range(members._MEMBER_CACHE_MAX_CONCURRENT):
            t = asyncio.create_task(asyncio.sleep(3600))
            members._member_cache_tasks.add(t)
            created.append(t)
        user = type(
            "U",
            (),
            {
                "id": 1,
                "is_bot": False,
                "first_name": "N",
                "username": None,
                "last_name": None,
            },
        )()
        update = type("Upd", (), {"effective_user": user})()
        ctx = type("Ctx", (), {"user_data": {}})()
        await members._update_member_cache(update, ctx)  # type: ignore[arg-type]
        assert len(members._member_cache_tasks) == members._MEMBER_CACHE_MAX_CONCURRENT
        for t in created:
            t.cancel()
        await asyncio.gather(*created, return_exceptions=True)
        members._member_cache_tasks.clear()

    asyncio.run(_scenario())
