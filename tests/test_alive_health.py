# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Health endpoint: mongodb verdict requires a fully CLOSED circuit."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

import tcbot.alive as alive_mod
from tcbot.utils.circuit_breaker import CircuitState


class _FakeCircuit:
    """Circuit double pinned to one state with a non-mutating peek_state."""

    def __init__(self, circuit_state: CircuitState) -> None:
        self._state = circuit_state

    def peek_state(self) -> CircuitState:
        return self._state

    @property
    def state(self) -> CircuitState:
        return self._state


class _FakeBreakers:
    """Break-alarm double exposing mongodb and telegram circuits."""

    def __init__(
        self, mongodb_state: CircuitState, telegram_state: CircuitState
    ) -> None:
        self.mongodb = _FakeCircuit(mongodb_state)
        self.telegram = _FakeCircuit(telegram_state)


class _FakeMongos:
    def __init__(self, *, connected: bool) -> None:
        self._connected = connected

    def is_connected(self) -> bool:
        return self._connected


class _FakeScheduler:
    def __init__(self, *, ready: bool) -> None:
        self._ready = ready

    def is_ready(self) -> bool:
        return self._ready


@pytest.fixture
def _health_no_io(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin every health input to the healthy state; tests override as needed."""

    monkeypatch.setattr(alive_mod, "mongos", _FakeMongos(connected=True))
    monkeypatch.setattr(alive_mod, "sched_mod", _FakeScheduler(ready=True))
    monkeypatch.setattr(
        alive_mod,
        "_cb",
        _FakeBreakers(CircuitState.CLOSED, CircuitState.CLOSED),
    )
    monkeypatch.setattr(alive_mod.redis_client, "client", lambda: None)
    monkeypatch.setattr(alive_mod, "cfg", SimpleNamespace(redis_url=""))
    monkeypatch.setattr(
        alive_mod,
        "utc_now",
        lambda: datetime(2026, 9, 14, 12, 0, 0, tzinfo=UTC),
    )


def _call_health() -> tuple[dict, int]:
    body, code, _ = alive_mod.health()
    return json.loads(body), code


def test_health_ok_when_all_closed(_health_no_io: None) -> None:
    payload, code = _call_health()
    assert payload["status"] == "ok"
    assert payload["mongodb"] == "ok"
    assert code == 200


def test_health_503_when_mongodb_open(
    _health_no_io: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        alive_mod,
        "_cb",
        _FakeBreakers(CircuitState.OPEN, CircuitState.CLOSED),
    )
    payload, code = _call_health()
    assert payload["status"] == "degraded"
    assert payload["mongodb"] == "error"
    assert code == 503


def test_health_503_when_mongodb_half_open(
    _health_no_io: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        alive_mod,
        "_cb",
        _FakeBreakers(CircuitState.HALF_OPEN, CircuitState.CLOSED),
    )
    payload, code = _call_health()
    assert payload["status"] == "degraded"
    assert payload["mongodb"] == "error"
    assert code == 503
