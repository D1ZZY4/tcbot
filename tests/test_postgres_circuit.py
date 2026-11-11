# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""PostgreSQL circuit: only transient errors count toward opening the circuit."""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy.exc import (
    DBAPIError,
    IntegrityError,
    InterfaceError,
    OperationalError,
    ProgrammingError,
)

from tcbot.database.engine import is_transient_db_error
from tcbot.utils.circuit_breaker import CircuitBreaker, CircuitOpenError, CircuitState

# * The circuit singleton is named after the service it guards.
_CIRCUIT_NAME: str = "postgres"


def test_classifier_labels_connectivity_transient() -> None:
    """A refused or dropped connection is worth retrying."""
    assert (
        is_transient_db_error(OperationalError("stmt", {}, Exception("down"))) is True
    )
    assert is_transient_db_error(InterfaceError("stmt", {}, Exception("reset"))) is True
    assert is_transient_db_error(TimeoutError("asyncio timeout")) is True
    assert is_transient_db_error(ConnectionError("socket closed")) is True


def test_classifier_uses_the_invalidated_connection_property() -> None:
    """The pool reports a dropped connection through the wrapper flag."""

    class _FakeDriverError(Exception):
        pass

    assert (
        is_transient_db_error(
            DBAPIError(
                "stmt",
                {},
                _FakeDriverError("connection is closed"),
                connection_invalidated=True,
            )
        )
        is True
    )


def test_classifier_labels_retryable_write_failures_transient() -> None:
    """A driver timeout inside the wrapper is the retryable write case."""
    assert (
        is_transient_db_error(
            DBAPIError("stmt", {}, ConnectionError("connection closed"))
        )
        is True
    )
    assert (
        is_transient_db_error(DBAPIError("stmt", {}, TimeoutError("read timeout")))
        is True
    )


def test_classifier_rejects_application_errors() -> None:
    """A constraint violation or a bad statement is an application bug."""
    assert (
        is_transient_db_error(IntegrityError("stmt", {}, Exception("duplicate")))
        is False
    )
    assert (
        is_transient_db_error(ProgrammingError("stmt", {}, Exception("syntax")))
        is False
    )
    assert is_transient_db_error(ValueError("bug")) is False
    assert is_transient_db_error(RuntimeError("bug")) is False
    assert is_transient_db_error(DBAPIError("stmt", {}, Exception("plain"))) is False


async def _boom(exc: Exception) -> None:
    raise exc


def test_non_transient_does_not_trip_circuit() -> None:
    cb = CircuitBreaker(_CIRCUIT_NAME, failure_threshold=2, recovery_timeout=60.0)

    async def _main() -> None:
        for _ in range(5):
            with pytest.raises(IntegrityError):
                await cb.call(
                    _boom(IntegrityError("stmt", {}, Exception("dup"))),
                    count_failure=is_transient_db_error,
                )

    asyncio.run(_main())
    assert cb.peek_state() is CircuitState.CLOSED


def test_transient_trips_circuit() -> None:
    cb = CircuitBreaker(_CIRCUIT_NAME, failure_threshold=2, recovery_timeout=60.0)

    async def _main() -> None:
        for _ in range(2):
            with pytest.raises(OperationalError):
                await cb.call(
                    _boom(OperationalError("stmt", {}, Exception("down"))),
                    count_failure=is_transient_db_error,
                )
        with pytest.raises(CircuitOpenError):
            await cb.call(
                _boom(OperationalError("stmt", {}, Exception("down"))),
                count_failure=is_transient_db_error,
            )

    asyncio.run(_main())
    assert cb.peek_state() is CircuitState.OPEN


def test_default_call_still_counts_everything() -> None:
    cb = CircuitBreaker(_CIRCUIT_NAME, failure_threshold=1, recovery_timeout=60.0)

    async def _main() -> None:
        with pytest.raises(ValueError):
            await cb.call(_boom(ValueError("bug")))

    asyncio.run(_main())
    assert cb.peek_state() is CircuitState.OPEN
