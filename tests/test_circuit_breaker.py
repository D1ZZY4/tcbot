# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Circuit breaker: peek_state() is read-only, state still lazily transitions."""

from __future__ import annotations

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
