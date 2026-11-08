# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Mongo circuit: only transient errors count toward opening the circuit."""

from __future__ import annotations

import asyncio

import pytest
from pymongo.errors import (
    ConnectionFailure,
    DuplicateKeyError,
    ExecutionTimeout,
    ServerSelectionTimeoutError,
    WriteConcernError,
)

from tcbot.database.mongos.client import is_transient_mongo_error
from tcbot.utils.circuit_breaker import CircuitBreaker, CircuitOpenError, CircuitState


def test_classifier_labels_connectivity_transient() -> None:
    assert is_transient_mongo_error(ConnectionFailure("down")) is True
    assert is_transient_mongo_error(ServerSelectionTimeoutError("no primary")) is True
    assert is_transient_mongo_error(ExecutionTimeout("slow")) is True
    assert is_transient_mongo_error(TimeoutError("asyncio timeout")) is True


def test_classifier_uses_client_side_timeout_property() -> None:
    class _FakeTimeout(Exception):
        timeout = True

    assert is_transient_mongo_error(_FakeTimeout("deadline")) is True


def test_classifier_labels_retryable_write_concern_transient() -> None:
    exc = WriteConcernError(
        "failover", details={"errorLabels": ["RetryableWriteError"]}
    )
    assert is_transient_mongo_error(exc) is True


def test_classifier_rejects_application_errors() -> None:
    assert is_transient_mongo_error(DuplicateKeyError("dup")) is False
    assert is_transient_mongo_error(ValueError("bug")) is False
    assert is_transient_mongo_error(RuntimeError("bug")) is False
    assert is_transient_mongo_error(WriteConcernError("plain")) is False
    assert is_transient_mongo_error(WriteConcernError("other")) is False


async def _boom(exc: Exception) -> None:
    raise exc


def test_non_transient_does_not_trip_circuit() -> None:
    cb = CircuitBreaker("mongodb", failure_threshold=2, recovery_timeout=60.0)

    async def _main() -> None:
        for _ in range(5):
            with pytest.raises(DuplicateKeyError):
                await cb.call(
                    _boom(DuplicateKeyError("dup")),
                    count_failure=is_transient_mongo_error,
                )

    asyncio.run(_main())
    assert cb.peek_state() is CircuitState.CLOSED


def test_transient_trips_circuit() -> None:
    cb = CircuitBreaker("mongodb", failure_threshold=2, recovery_timeout=60.0)

    async def _main() -> None:
        for _ in range(2):
            with pytest.raises(ConnectionFailure):
                await cb.call(
                    _boom(ConnectionFailure("down")),
                    count_failure=is_transient_mongo_error,
                )
        with pytest.raises(CircuitOpenError):
            await cb.call(
                _boom(ConnectionFailure("down")),
                count_failure=is_transient_mongo_error,
            )

    asyncio.run(_main())
    assert cb.peek_state() is CircuitState.OPEN


def test_default_call_still_counts_everything() -> None:
    cb = CircuitBreaker("mongodb", failure_threshold=1, recovery_timeout=60.0)

    async def _main() -> None:
        with pytest.raises(ValueError):
            await cb.call(_boom(ValueError("bug")))

    asyncio.run(_main())
    assert cb.peek_state() is CircuitState.OPEN
