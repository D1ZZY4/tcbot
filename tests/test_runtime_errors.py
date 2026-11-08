# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Runtime error handlers: suppressed outages never ship a report."""

from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace
from typing import Any

from pymongo.errors import ServerSelectionTimeoutError

from tcbot.runtime import errors as runtime_errors
from tcbot.utils import error_reporter
from tcbot.utils.circuit_breaker import CircuitOpenError


class _FakeTask:
    def add_done_callback(self, _cb: Any) -> None:
        return None


class _FakeLoop:
    def __init__(self) -> None:
        self.tasks_created: int = 0

    def create_task(self, coro: Any) -> _FakeTask:
        self.tasks_created += 1
        coro.close()
        return _FakeTask()


class _FakeFuture:
    def __init__(self, exc: BaseException | None, *, cancelled: bool = False) -> None:
        self._exc = exc
        self._cancelled = cancelled

    def done(self) -> bool:
        return True

    def cancelled(self) -> bool:
        return self._cancelled

    def exception(self) -> BaseException | None:
        if self._cancelled:
            raise asyncio.CancelledError()
        return self._exc


def test_asyncio_handler_extracts_and_suppresses_mongo(
    monkeypatch: Any,
) -> None:
    """A never-retrieved ServerSelectionTimeoutError is suppressed, not shipped."""
    loop = _FakeLoop()
    handler = runtime_errors._make_asyncio_exc_handler(loop)  # type: ignore[arg-type]

    reported: list[Any] = []

    async def _fake_report(exc: BaseException, context: Any = None) -> None:
        reported.append((exc, context))

    monkeypatch.setattr(error_reporter, "report_exc", _fake_report)
    # * Keep the park path quiet: the extracted outage is not an auth failure.
    monkeypatch.setattr(
        "tcbot.runtime.errors.mtproto_mod.is_auth_key_duplicated",
        lambda exc: False,
    )

    handler(
        loop,  # type: ignore[arg-type]
        {
            "exception": None,
            "message": "Task exception was never retrieved",
            "task": _FakeFuture(ServerSelectionTimeoutError("no primary")),
        },
    )
    assert loop.tasks_created == 0
    assert reported == []


def test_asyncio_handler_extracts_and_suppresses_circuit(
    monkeypatch: Any,
) -> None:
    """A never-retrieved CircuitOpenError is suppressed, not shipped."""
    loop = _FakeLoop()
    handler = runtime_errors._make_asyncio_exc_handler(loop)  # type: ignore[arg-type]

    reported: list[Any] = []

    async def _fake_report(exc: BaseException, context: Any = None) -> None:
        reported.append(exc)

    monkeypatch.setattr(error_reporter, "report_exc", _fake_report)
    handler(
        loop,  # type: ignore[arg-type]
        {
            "exception": None,
            "message": "Task exception was never retrieved",
            "future": _FakeFuture(
                CircuitOpenError("Circuit [mongodb] is OPEN; call rejected.")
            ),
        },
    )
    assert loop.tasks_created == 0
    assert reported == []


def test_asyncio_handler_direct_circuit_suppressed(monkeypatch: Any) -> None:
    """A directly-set CircuitOpenError is suppressed without a report task."""
    loop = _FakeLoop()
    handler = runtime_errors._make_asyncio_exc_handler(loop)  # type: ignore[arg-type]
    handler(
        loop,  # type: ignore[arg-type]
        {
            "exception": CircuitOpenError("Circuit [mongodb] is OPEN"),
            "message": "boom",
        },
    )
    assert loop.tasks_created == 0


def test_asyncio_handler_extracted_error_reports_real_type(monkeypatch: Any) -> None:
    """A non-suppressed extracted exception ships as itself, not RuntimeError(detail)."""
    loop = _FakeLoop()
    handler = runtime_errors._make_asyncio_exc_handler(loop)  # type: ignore[arg-type]

    reported: list[Any] = []

    async def _fake_report(exc: BaseException, context: Any = None) -> None:
        reported.append(exc)

    monkeypatch.setattr(error_reporter, "report_exc", _fake_report)
    orig_create = loop.create_task

    def _create(coro: Any) -> Any:
        # * The coroutine wraps report_exc(exc, context=detail); run it to
        # * capture what would have shipped. report_exc is stubbed above.
        async def _drain() -> None:
            await coro

        asyncio.run(_drain())
        return orig_create  # type: ignore[return-value]

    monkeypatch.setattr(loop, "create_task", _create)
    monkeypatch.setattr(
        "tcbot.runtime.errors.mtproto_mod.is_auth_key_duplicated",
        lambda exc: False,
    )

    boom = ValueError("boom")
    handler(
        loop,  # type: ignore[arg-type]
        {
            "exception": None,
            "message": "Task exception was never retrieved",
            "task": _FakeFuture(boom),
        },
    )
    # * The handler scheduled one report task (the fake ran it inline).
    assert reported and reported[0] is boom
    assert not isinstance(reported[0], RuntimeError)


def test_asyncio_handler_cancelled_future_is_benign(monkeypatch: Any) -> None:
    """A cancelled task future never reaches the report path."""
    loop = _FakeLoop()
    handler = runtime_errors._make_asyncio_exc_handler(loop)  # type: ignore[arg-type]
    handler(
        loop,  # type: ignore[arg-type]
        {
            "exception": None,
            "message": "Task exception was never retrieved",
            "task": _FakeFuture(None, cancelled=True),
        },
    )
    assert loop.tasks_created == 0


def test_error_handler_suppresses_mongo_outage(monkeypatch: Any, caplog: Any) -> None:
    """The PTB handler path drops ServerSelectionTimeoutError before log.error."""
    reported: list[Any] = []

    async def _fake_report(exc: BaseException, context: Any = None) -> None:
        reported.append(exc)

    monkeypatch.setattr(error_reporter, "report_exc", _fake_report)

    ctx = SimpleNamespace(error=ServerSelectionTimeoutError("no primary"))
    with caplog.at_level(logging.DEBUG, logger="tcbot.runtime.errors"):
        asyncio.run(runtime_errors._error_handler(object(), ctx))  # type: ignore[arg-type]
    assert reported == []
    assert "Unhandled exception for update" not in caplog.text


def test_error_handler_suppresses_circuit_open(monkeypatch: Any, caplog: Any) -> None:
    """The PTB handler path drops CircuitOpenError before log.error."""
    reported: list[Any] = []

    async def _fake_report(exc: BaseException, context: Any = None) -> None:
        reported.append(exc)

    monkeypatch.setattr(error_reporter, "report_exc", _fake_report)

    ctx = SimpleNamespace(
        error=CircuitOpenError("Circuit [mongodb] is OPEN; call rejected.")
    )
    with caplog.at_level(logging.DEBUG, logger="tcbot.runtime.errors"):
        asyncio.run(runtime_errors._error_handler(object(), ctx))  # type: ignore[arg-type]
    assert reported == []
    assert "Unhandled exception for update" not in caplog.text
