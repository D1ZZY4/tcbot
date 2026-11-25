# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Shutdown must close every client even when one step reports cancellation."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from tcbot import __main__ as main_mod
from tcbot.database import mtproto as mtproto_mod
from tcbot.database import redis_client
from tcbot.database import scheduler as sched_mod
from tcbot.modules.helper.extraction import refresh as identity_refresh
from tcbot.modules.helper.pipelines import connect_common
from tcbot.modules.helper.pipelines.errors import report as error_reporter


def _stub_shutdown_steps(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace every drain with a no-op, leaving the final teardown under test."""

    async def _noop(*args: Any, **kwargs: Any) -> None:
        _ = (args, kwargs)
        return

    no_drain = SimpleNamespace(drain=_noop)
    monkeypatch.setattr(main_mod, "shutdown_dispatcher", _noop)
    monkeypatch.setattr(sched_mod, "stop", _noop)
    monkeypatch.setattr(main_mod, "_asyncio_report_tasks", no_drain)
    monkeypatch.setattr(identity_refresh, "identity_refresh_tasks", no_drain)
    monkeypatch.setattr(connect_common, "harvest_tasks", no_drain)
    monkeypatch.setattr(main_mod, "drain_proof_sessions", _noop)
    monkeypatch.setattr(error_reporter, "drain_pending", _noop)
    monkeypatch.setattr(main_mod, "_member_cache_tasks", no_drain)
    monkeypatch.setattr(main_mod, "_startup_tasks", no_drain)
    monkeypatch.setattr(main_mod, "drain_redis_mutations", _noop)


def test_database_closes_after_a_cancelled_shutdown_step(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A cancelled step propagates only after the database connection is closed."""
    _stub_shutdown_steps(monkeypatch)
    closed: list[bool] = []

    async def _cancelled_close() -> Any:
        return asyncio.CancelledError()

    async def _close_database() -> None:
        closed.append(True)

    monkeypatch.setattr(redis_client, "close", _cancelled_close)
    monkeypatch.setattr(mtproto_mod, "stop", _cancelled_close)
    monkeypatch.setattr(main_mod, "close_database", _close_database)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(main_mod._shutdown_subsystems())

    assert closed == [True]


def test_clients_close_when_an_early_drain_is_cancelled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A second cancellation during a drain must not skip client disposal."""
    _stub_shutdown_steps(monkeypatch)
    closed: list[str] = []

    async def _cancelled_drain() -> None:
        raise asyncio.CancelledError()

    async def _close(name: str) -> None:
        closed.append(name)

    async def _close_redis() -> None:
        await _close("redis")

    async def _close_mtproto() -> None:
        await _close("mtproto")

    async def _close_database() -> None:
        await _close("database")

    monkeypatch.setattr(main_mod, "shutdown_dispatcher", _cancelled_drain)
    monkeypatch.setattr(redis_client, "close", _close_redis)
    monkeypatch.setattr(mtproto_mod, "stop", _close_mtproto)
    monkeypatch.setattr(main_mod, "close_database", _close_database)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(main_mod._shutdown_subsystems())

    assert closed == ["redis", "mtproto", "database"]


def test_database_closes_when_disposal_task_is_cancelled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A second cancellation during client disposal must still close the DB."""
    _stub_shutdown_steps(monkeypatch)
    closed: list[bool] = []
    disposal_started = asyncio.Event()

    async def _slow_close() -> None:
        disposal_started.set()
        await asyncio.sleep(10)

    async def _close_database() -> None:
        closed.append(True)

    monkeypatch.setattr(redis_client, "close", _slow_close)
    monkeypatch.setattr(mtproto_mod, "stop", _slow_close)
    monkeypatch.setattr(main_mod, "close_database", _close_database)

    async def _run() -> None:
        task = asyncio.create_task(main_mod._shutdown_subsystems())
        await disposal_started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(_run())

    assert closed == [True]
