# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Circuit breaker: peek_state() is read-only, state still lazily transitions."""

from __future__ import annotations

import asyncio

import pytest

from tcbot.utils.circuit_breaker import CircuitBreaker, CircuitState


def _open_breaker(cb: CircuitBreaker) -> CircuitBreaker:
    """Open *cb* and force the recovery window to have elapsed."""
    cb.record_failure()
    cb._opened_at = 0.0
    return cb


def test_peek_state_does_not_transition_open() -> None:
    cb = _open_breaker(CircuitBreaker("x", failure_threshold=1, recovery_timeout=0.01))
    assert cb.peek_state() is CircuitState.OPEN
    assert cb._state is CircuitState.OPEN


def test_state_property_still_transitions() -> None:
    cb = _open_breaker(CircuitBreaker("x", failure_threshold=1, recovery_timeout=0.01))
    assert cb.state is CircuitState.HALF_OPEN


def test_peek_state_closed() -> None:
    cb = CircuitBreaker("x", failure_threshold=1, recovery_timeout=0.01)
    assert cb.peek_state() is CircuitState.CLOSED
    assert cb._state is CircuitState.CLOSED


def test_a_reached_service_probe_closes_a_half_open_circuit() -> None:
    """A refusal proves the transport works, so the circuit must close.

    Staying HALF_OPEN admits one caller at a time and rejects every
    concurrent one, which serialises the database layer and starves a
    federation fan-out after any breaker trip.
    """
    cb = _open_breaker(CircuitBreaker("x", failure_threshold=1, recovery_timeout=0.01))
    assert cb.state is CircuitState.HALF_OPEN

    cb.release_probe(reached_service=True)

    assert cb._state is CircuitState.CLOSED
    assert cb.try_acquire() is True


def test_a_non_transient_exception_closes_a_half_open_circuit() -> None:
    """The predicate-rejected path in call() must close the circuit too."""
    cb = _open_breaker(CircuitBreaker("x", failure_threshold=1, recovery_timeout=0.01))

    async def _refused() -> str:
        raise ValueError("refused")

    def _not_transient(exc: Exception) -> bool:
        return False

    with pytest.raises(ValueError):
        asyncio.run(cb.call(_refused(), count_failure=_not_transient))

    assert cb._state is CircuitState.CLOSED
    assert cb.try_acquire() is True


def test_a_transient_failure_reopens_a_half_open_circuit() -> None:
    """A genuine transport failure must send the circuit back to OPEN."""
    cb = _open_breaker(CircuitBreaker("x", failure_threshold=1, recovery_timeout=0.01))
    assert cb.state is CircuitState.HALF_OPEN

    async def _boom() -> str:
        raise TimeoutError("down")

    def _transient(exc: Exception) -> bool:
        return True

    with pytest.raises(TimeoutError):
        asyncio.run(cb.call(_boom(), count_failure=_transient))

    assert cb._state is CircuitState.OPEN
    assert cb.try_acquire() is False


def test_a_nested_call_counts_one_failure_once() -> None:
    """A failure that passes through two breakers is one failure.

    A helper that already runs through the breaker must not be wrapped in
    a second one: the exception is the same object on both levels, so
    counting it twice would trip the circuit after fewer real failures
    than the threshold promises.
    """
    cb = CircuitBreaker("x", failure_threshold=5, recovery_timeout=60.0)
    error = TimeoutError("down")

    def _transient(exc: Exception) -> bool:
        return True

    async def _inner() -> None:
        raise error

    async def _outer() -> None:
        await cb.call(_inner(), count_failure=_transient)

    with pytest.raises(TimeoutError):
        asyncio.run(cb.call(_outer(), count_failure=_transient))

    assert cb._failure_count == 1


def test_two_separate_failures_still_count_twice() -> None:
    """Two distinct failures must not collapse into one count."""
    cb = CircuitBreaker("x", failure_threshold=5, recovery_timeout=60.0)

    def _transient(exc: Exception) -> bool:
        return True

    async def _boom() -> None:
        raise TimeoutError("down")

    async def _main() -> None:
        for _ in range(2):
            with pytest.raises(TimeoutError):
                await cb.call(_boom(), count_failure=_transient)

    asyncio.run(_main())
    assert cb._failure_count == 2


def test_a_concurrent_success_does_not_clear_the_dedup_marker() -> None:
    """A success between the two levels must not make the failure count twice.

    The failure travels out of the inner breaker, through a rollback that
    costs a round trip, and only then reaches the outer breaker. A
    successful call that lands in that window used to clear the marker,
    so the same failure was counted on both levels.
    """
    cb = CircuitBreaker("x", failure_threshold=5, recovery_timeout=60.0)
    error = TimeoutError("down")

    def _transient(exc: Exception) -> bool:
        return True

    async def _inner() -> None:
        raise error

    async def _outer() -> None:
        try:
            await cb.call(_inner(), count_failure=_transient)
        except TimeoutError:
            # * The concurrent success lands while the failure unwinds.
            await cb.call(_ok(), count_failure=_transient)
            raise

    async def _ok() -> str:
        return "ok"

    with pytest.raises(TimeoutError):
        asyncio.run(cb.call(_outer(), count_failure=_transient))

    assert cb._failure_count == 1
