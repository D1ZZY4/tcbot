# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Runtime error handlers: suppressed outages never ship a report."""

from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace
from typing import Any

from pyrogram.session.session import AuthKeyNotFound
from sqlalchemy.exc import OperationalError

from tcbot import __main__ as runtime_errors
from tcbot import error_reporter
from tcbot.utils.circuit_breaker import CircuitOpenError


class _FakeTracker:
    """Stand-in for ``TaskTracker`` that records the scheduled coroutines."""

    def __init__(self) -> None:
        self.spawned: list[Any] = []

    def spawn(self, coro: Any) -> bool:
        self.spawned.append(coro)
        return True

    async def drain(self, **_kwargs: Any) -> None:
        return None

    @property
    def tasks_created(self) -> int:
        return len(self.spawned)

    def run_spawned(self) -> None:
        """Run every scheduled coroutine to completion."""
        while self.spawned:
            coro = self.spawned.pop(0)
            asyncio.run(coro)

    def clear(self) -> None:
        """Drop the scheduled coroutines without running them."""
        while self.spawned:
            coro = self.spawned.pop(0)
            coro.close()


def _database_outage() -> OperationalError:
    """Return the error a refused PostgreSQL connection produces."""
    return OperationalError("SELECT 1", {}, Exception("connection refused"))


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


def test_asyncio_handler_extracts_and_suppresses_database_outage(
    monkeypatch: Any,
) -> None:
    """A never-retrieved database outage is suppressed, not shipped."""
    tracker = _FakeTracker()
    monkeypatch.setattr(runtime_errors, "_asyncio_report_tasks", tracker)
    handler = runtime_errors._make_asyncio_exc_handler()

    reported: list[Any] = []

    async def _fake_report(exc: BaseException, context: Any = None) -> None:
        reported.append((exc, context))

    monkeypatch.setattr(error_reporter, "report_exc", _fake_report)
    # * Keep the park path quiet: the extracted outage is not an auth failure.
    monkeypatch.setattr(
        "tcbot.__main__.mtproto_mod.is_auth_key_duplicated",
        lambda exc: False,
    )

    handler(
        None,  # type: ignore[arg-type]
        {
            "exception": None,
            "message": "Task exception was never retrieved",
            "task": _FakeFuture(_database_outage()),
        },
    )
    assert tracker.tasks_created == 0
    assert reported == []


def test_asyncio_handler_extracts_and_suppresses_circuit(
    monkeypatch: Any,
) -> None:
    """A never-retrieved CircuitOpenError is suppressed, not shipped."""
    tracker = _FakeTracker()
    monkeypatch.setattr(runtime_errors, "_asyncio_report_tasks", tracker)
    handler = runtime_errors._make_asyncio_exc_handler()

    reported: list[Any] = []

    async def _fake_report(exc: BaseException, context: Any = None) -> None:
        reported.append(exc)

    monkeypatch.setattr(error_reporter, "report_exc", _fake_report)
    handler(
        None,  # type: ignore[arg-type]
        {
            "exception": None,
            "message": "Task exception was never retrieved",
            "future": _FakeFuture(
                CircuitOpenError("Circuit [postgres] is OPEN; call rejected.")
            ),
        },
    )
    assert tracker.tasks_created == 0
    assert reported == []


def test_asyncio_handler_direct_circuit_suppressed(monkeypatch: Any) -> None:
    """A directly-set CircuitOpenError is suppressed without a report task."""
    tracker = _FakeTracker()
    monkeypatch.setattr(runtime_errors, "_asyncio_report_tasks", tracker)
    handler = runtime_errors._make_asyncio_exc_handler()
    handler(
        None,  # type: ignore[arg-type]
        {
            "exception": CircuitOpenError("Circuit [postgres] is OPEN"),
            "message": "boom",
        },
    )
    assert tracker.tasks_created == 0


def test_asyncio_handler_extracted_error_reports_real_type(monkeypatch: Any) -> None:
    """A non-suppressed extracted exception ships as itself, not RuntimeError(detail)."""
    tracker = _FakeTracker()
    monkeypatch.setattr(runtime_errors, "_asyncio_report_tasks", tracker)
    handler = runtime_errors._make_asyncio_exc_handler()

    reported: list[Any] = []

    async def _fake_report(exc: BaseException, context: Any = None) -> None:
        reported.append(exc)

    monkeypatch.setattr(error_reporter, "report_exc", _fake_report)
    monkeypatch.setattr(
        "tcbot.__main__.mtproto_mod.is_auth_key_duplicated",
        lambda exc: False,
    )

    boom = ValueError("boom")
    handler(
        None,  # type: ignore[arg-type]
        {
            "exception": None,
            "message": "Task exception was never retrieved",
            "task": _FakeFuture(boom),
        },
    )
    # * The handler scheduled one report task; running it captures what
    # * would have shipped.
    tracker.run_spawned()
    assert reported and reported[0] is boom
    assert not isinstance(reported[0], RuntimeError)


def test_asyncio_handler_cancelled_future_is_benign(monkeypatch: Any) -> None:
    """A cancelled task future never reaches the report path."""
    tracker = _FakeTracker()
    monkeypatch.setattr(runtime_errors, "_asyncio_report_tasks", tracker)
    handler = runtime_errors._make_asyncio_exc_handler()
    handler(
        None,  # type: ignore[arg-type]
        {
            "exception": None,
            "message": "Task exception was never retrieved",
            "task": _FakeFuture(None, cancelled=True),
        },
    )
    assert tracker.tasks_created == 0


def test_asyncio_handler_auth_key_not_found_parks_once(monkeypatch: Any) -> None:
    """A dead auth key parks MTProto and ships one card, then stays quiet."""
    tracker = _FakeTracker()
    monkeypatch.setattr(runtime_errors, "_asyncio_report_tasks", tracker)
    handler = runtime_errors._make_asyncio_exc_handler()

    async def _fake_park() -> None:
        return None

    monkeypatch.setattr(
        "tcbot.__main__.mtproto_mod.handle_auth_failure",
        _fake_park,
    )
    monkeypatch.setattr(
        "tcbot.__main__.mtproto_mod.is_auth_dead",
        lambda: False,
    )

    exc = AuthKeyNotFound("Auth key not found in the system.")
    handler(
        None,  # type: ignore[arg-type]
        {
            "exception": None,
            "message": "Task exception was never retrieved",
            "task": _FakeFuture(exc),
        },
    )
    # * One park task plus one loud report task for the first sighting.
    assert tracker.tasks_created == 2

    monkeypatch.setattr(
        "tcbot.__main__.mtproto_mod.is_auth_dead",
        lambda: True,
    )
    tracker.clear()
    handler(
        None,  # type: ignore[arg-type]
        {
            "exception": None,
            "message": "Task exception was never retrieved",
            "task": _FakeFuture(exc),
        },
    )
    assert tracker.tasks_created == 0


def test_error_handler_suppresses_database_outage(
    monkeypatch: Any, caplog: Any
) -> None:
    """The PTB handler path drops a database outage before log.error."""
    reported: list[Any] = []

    async def _fake_report(exc: BaseException, context: Any = None) -> None:
        reported.append(exc)

    monkeypatch.setattr(error_reporter, "report_exc", _fake_report)

    ctx = SimpleNamespace(error=_database_outage())
    with caplog.at_level(logging.DEBUG, logger="tcbot.__main__"):
        asyncio.run(runtime_errors._error_handler(object(), ctx))  # type: ignore[arg-type]
    assert reported == []
    assert "Unhandled exception for update" not in caplog.text


def test_error_handler_reports_when_benign_check_raises(
    monkeypatch: Any, caplog: Any
) -> None:
    """If the benign predicate itself faults, the update still ships loudly."""
    reported: list[Any] = []

    async def _fake_report(exc: BaseException, context: Any = None) -> None:
        reported.append(exc)

    def _boom(exc: BaseException) -> bool:
        raise RuntimeError("benign predicate offline")

    monkeypatch.setattr(error_reporter, "report_exc", _fake_report)
    monkeypatch.setattr(error_reporter, "_benign", _boom)

    ctx = SimpleNamespace(error=ValueError("boom"))
    with caplog.at_level(logging.DEBUG, logger="tcbot.__main__"):
        asyncio.run(runtime_errors._error_handler(object(), ctx))  # type: ignore[arg-type]
    assert len(reported) == 1 and isinstance(reported[0], ValueError)
    assert "Unhandled exception for update" in caplog.text
    assert "benign check failed" in caplog.text


def test_error_handler_suppresses_circuit_open(monkeypatch: Any, caplog: Any) -> None:
    """The PTB handler path drops CircuitOpenError before log.error."""
    reported: list[Any] = []

    async def _fake_report(exc: BaseException, context: Any = None) -> None:
        reported.append(exc)

    monkeypatch.setattr(error_reporter, "report_exc", _fake_report)

    ctx = SimpleNamespace(
        error=CircuitOpenError("Circuit [postgres] is OPEN; call rejected.")
    )
    with caplog.at_level(logging.DEBUG, logger="tcbot.__main__"):
        asyncio.run(runtime_errors._error_handler(object(), ctx))  # type: ignore[arg-type]
    assert reported == []
    assert "Unhandled exception for update" not in caplog.text
