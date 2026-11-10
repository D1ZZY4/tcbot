# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Database call transport: bounded wait, dedicated pool, context propagation."""

from __future__ import annotations

import asyncio
import contextvars
import threading
import time
from typing import Any

import pytest

from tcbot.database import mongos
from tcbot.utils.circuit_breaker import CircuitOpenError
from tcbot.utils.circuit_breaker import mongodb as mongo_circuit

_scope: contextvars.ContextVar[str] = contextvars.ContextVar("scope", default="none")


@pytest.fixture(autouse=True)
def _reset_circuit() -> None:
    """Reset the MongoDB circuit so one test cannot open it for the others."""
    mongo_circuit.reset()


def test_db_call_returns_the_worker_result() -> None:
    """A successful operation returns its value."""

    async def _run() -> str:
        return await mongos.db_call(lambda: "value")

    assert asyncio.run(_run()) == "value"


def test_db_call_propagates_the_worker_context() -> None:
    """The request context survives into the worker thread."""
    seen: list[str] = []

    def _op() -> None:
        seen.append(_scope.get())

    async def _run() -> None:
        token = _scope.set("request-42")
        try:
            await mongos.db_call(_op)
        finally:
            _scope.reset(token)

    asyncio.run(_run())
    assert seen == ["request-42"]


def test_db_call_times_out_and_releases_the_caller() -> None:
    """A hung operation must not hang the caller past its budget."""
    started = threading.Event()

    def _slow() -> None:
        started.set()
        time.sleep(2.0)

    async def _run() -> None:
        with pytest.raises(TimeoutError):
            await mongos.db_call(_slow, timeout=0.2)
        assert started.is_set()

    asyncio.run(_run())


def test_db_call_without_timeout_waits_for_the_worker() -> None:
    """``timeout=None`` lets a long operation finish."""
    result: list[str] = []

    def _slow() -> None:
        time.sleep(0.2)
        result.append("done")

    async def _run() -> None:
        await mongos.db_call(_slow, timeout=None)

    asyncio.run(_run())
    assert result == ["done"]


def test_db_call_runs_on_the_dedicated_pool() -> None:
    """Database work must not occupy the event loop's default executor."""
    threads: list[str] = []

    def _op() -> None:
        threads.append(threading.current_thread().name)

    async def _run() -> None:
        await mongos.db_call(_op)

    asyncio.run(_run())
    assert threads
    assert all(name.startswith("tcbot-db") for name in threads)


def test_db_call_propagates_worker_exceptions() -> None:
    """An application error propagates unchanged and does not open the circuit."""

    def _boom() -> None:
        raise ValueError("bad write")

    async def _run() -> None:
        with pytest.raises(ValueError, match="bad write"):
            await mongos.db_call(_boom)

    asyncio.run(_run())
    assert mongo_circuit.peek_state().value == "closed"


def test_db_call_rejects_when_the_circuit_is_open() -> None:
    """An open circuit rejects the call without touching the worker pool."""

    def _op() -> None:
        raise TimeoutError("mongo unreachable")

    async def _run() -> None:
        for _ in range(5):
            with pytest.raises(TimeoutError):
                await mongos.db_call(_op)
        with pytest.raises(CircuitOpenError):
            await mongos.db_call(_op)

    asyncio.run(_run())


def test_db_pool_is_recreated_after_close() -> None:
    """A closed pool is rebuilt lazily so a later start still works."""

    async def _run() -> Any:
        first = mongos._db_pool()
        mongos.close()
        second = mongos._db_pool()
        return first, second

    first, second = asyncio.run(_run())
    assert first is not second
