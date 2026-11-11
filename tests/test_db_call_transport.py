# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Database call transport: bounded wait, shared pool, context propagation."""

from __future__ import annotations

import asyncio
import contextvars
import threading
from typing import Any

import pytest

from tcbot.database import engine as engine_module
from tcbot.utils.circuit_breaker import CircuitOpenError
from tcbot.utils.circuit_breaker import postgres as postgres_circuit

_scope: contextvars.ContextVar[str] = contextvars.ContextVar("scope", default="none")

# * The URL the fake engine is built with: the test never opens a socket.
_TEST_URL: str = "postgresql://tcbot:dummy@127.0.0.1:1/tcbot_placeholder"


class _FakeAsyncEngine:
    """Async engine double: records the disposal, opens no connection."""

    def __init__(self) -> None:
        self.disposed = False

    async def dispose(self) -> None:
        self.disposed = True


@pytest.fixture(autouse=True)
def _reset_circuit() -> None:
    """Reset the PostgreSQL circuit so one test cannot open it for the others."""
    postgres_circuit.reset()


@pytest.fixture
def _restore_engine_state() -> Any:
    """Restore the published engine so a test cannot leak it into the next."""
    previous_engine = engine_module._engine
    previous_factory = engine_module._session_factory
    try:
        yield
    finally:
        engine_module._engine = previous_engine
        engine_module._session_factory = previous_factory


def test_db_call_returns_the_operation_result() -> None:
    """A successful operation returns its value."""

    async def _run() -> str:
        return await engine_module.db_call(lambda: _value("value"))

    assert asyncio.run(_run()) == "value"


async def _value(text: str) -> str:
    return text


def test_db_call_propagates_the_caller_context() -> None:
    """The request context reaches the database operation."""
    seen: list[str] = []

    async def _op() -> None:
        seen.append(_scope.get())

    async def _run() -> None:
        token = _scope.set("request-42")
        try:
            await engine_module.db_call(_op)
        finally:
            _scope.reset(token)

    asyncio.run(_run())
    assert seen == ["request-42"]


def test_db_call_times_out_and_releases_the_caller() -> None:
    """A hung operation must not hang the caller past its budget."""
    started = asyncio.Event()

    async def _slow() -> None:
        started.set()
        await asyncio.sleep(2.0)

    async def _run() -> None:
        with pytest.raises(TimeoutError):
            await engine_module.db_call(_slow, timeout=0.2)
        assert started.is_set()

    asyncio.run(_run())


def test_db_call_without_timeout_waits_for_the_operation() -> None:
    """``timeout=None`` lets a long operation finish."""
    result: list[str] = []

    async def _slow() -> None:
        await asyncio.sleep(0.2)
        result.append("done")

    async def _run() -> None:
        await engine_module.db_call(_slow, timeout=None)

    asyncio.run(_run())
    assert result == ["done"]


def test_db_call_runs_on_the_event_loop() -> None:
    """Database work must not occupy a worker thread of the default executor.

    The async driver talks to the server from the event loop, so the
    operation runs on the loop thread and never blocks the executor the
    rest of the application shares.
    """
    threads: list[int] = []
    loop_thread = threading.get_ident()

    async def _op() -> None:
        threads.append(threading.get_ident())

    async def _run() -> None:
        await engine_module.db_call(_op)

    asyncio.run(_run())
    assert threads == [loop_thread]


def test_db_call_propagates_operation_exceptions() -> None:
    """An application error propagates unchanged and does not open the circuit."""

    async def _boom() -> None:
        raise ValueError("bad write")

    async def _run() -> None:
        with pytest.raises(ValueError, match="bad write"):
            await engine_module.db_call(_boom)

    asyncio.run(_run())
    assert postgres_circuit.peek_state().value == "closed"


def test_db_call_rejects_when_the_circuit_is_open() -> None:
    """An open circuit rejects the call without touching the database."""
    calls = 0

    async def _op() -> None:
        nonlocal calls
        calls += 1
        raise TimeoutError("database unreachable")

    async def _run() -> None:
        for _ in range(5):
            with pytest.raises(TimeoutError):
                await engine_module.db_call(_op)
        with pytest.raises(CircuitOpenError):
            await engine_module.db_call(_op)

    asyncio.run(_run())
    assert calls == 5


def test_the_engine_is_recreated_after_close(
    monkeypatch: pytest.MonkeyPatch, _restore_engine_state: None
) -> None:
    """A closed engine is rebuilt so a later start still works."""
    built: list[_FakeAsyncEngine] = []

    def _fake_create_async_engine(_url: str, **_kwargs: Any) -> _FakeAsyncEngine:
        fake = _FakeAsyncEngine()
        built.append(fake)
        return fake

    def _noop_migrations(_url: str) -> None:
        return None

    async def _noop_ping() -> None:
        return None

    monkeypatch.setattr(engine_module, "create_async_engine", _fake_create_async_engine)
    monkeypatch.setattr(
        engine_module.migrations, "upgrade_head", _noop_migrations, raising=True
    )
    monkeypatch.setattr(engine_module, "_ping", _noop_ping)
    monkeypatch.setattr(engine_module, "_database_url", lambda: _TEST_URL)

    async def _run() -> tuple[Any, Any]:
        assert engine_module.is_connected() is False
        with pytest.raises(RuntimeError, match="not initialised"):
            engine_module.engine()
        await engine_module.connect()
        first = engine_module.engine()
        await engine_module.close()
        assert engine_module.is_connected() is False
        with pytest.raises(RuntimeError, match="not initialised"):
            engine_module.engine()
        await engine_module.connect()
        return first, engine_module.engine()

    first, second = asyncio.run(_run())
    assert first is not second
    assert built[0].disposed is True
