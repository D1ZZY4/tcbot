# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Health endpoint: the database verdict requires a fully CLOSED circuit."""

from __future__ import annotations

import socket
from datetime import UTC, datetime
from types import SimpleNamespace

import msgspec
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
    """Break-alarm double exposing the postgres and telegram circuits."""

    def __init__(
        self, postgres_state: CircuitState, telegram_state: CircuitState
    ) -> None:
        self.postgres = _FakeCircuit(postgres_state)
        self.telegram = _FakeCircuit(telegram_state)


class _FakeEngine:
    """Engine double pinned to one connection state."""

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
    monkeypatch.setattr(alive_mod, "db_engine", _FakeEngine(connected=True))
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
    return msgspec.json.decode(body), code


def test_health_ok_when_all_closed(_health_no_io: None) -> None:
    payload, code = _call_health()
    assert payload["status"] == "ok"
    assert payload["database"] == "ok"
    assert code == 200


def test_health_503_when_database_circuit_open(
    _health_no_io: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        alive_mod,
        "_cb",
        _FakeBreakers(CircuitState.OPEN, CircuitState.CLOSED),
    )
    payload, code = _call_health()
    assert payload["status"] == "degraded"
    assert payload["database"] == "error"
    assert code == 503


def test_health_503_when_database_circuit_half_open(
    _health_no_io: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        alive_mod,
        "_cb",
        _FakeBreakers(CircuitState.HALF_OPEN, CircuitState.CLOSED),
    )
    payload, code = _call_health()
    assert payload["status"] == "degraded"
    assert payload["database"] == "error"
    assert code == 503


def _patch_redis(monkeypatch: pytest.MonkeyPatch, *, liveness: object) -> None:
    monkeypatch.setattr(alive_mod, "cfg", SimpleNamespace(redis_url="redis://local"))
    monkeypatch.setattr(alive_mod.redis_client, "liveness", lambda: liveness)


def test_redis_status_ok_when_liveness_true(
    _health_no_io: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_redis(monkeypatch, liveness=True)
    payload, code = _call_health()
    assert payload["redis"] == "ok"
    assert code == 200


def test_redis_status_error_when_liveness_false(
    _health_no_io: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_redis(monkeypatch, liveness=False)
    payload, code = _call_health()
    assert payload["redis"] == "error"
    assert code == 200


def test_redis_status_unknown_when_liveness_none(
    _health_no_io: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_redis(monkeypatch, liveness=None)
    payload, code = _call_health()
    assert payload["redis"] == "unknown"
    assert code == 200


def test_redis_status_disabled_when_no_redis(_health_no_io: None) -> None:
    payload, code = _call_health()
    assert payload["redis"] == "disabled"
    assert code == 200


def test_health_503_when_scheduler_not_ready(
    _health_no_io: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(alive_mod, "sched_mod", _FakeScheduler(ready=False))
    payload, code = _call_health()
    assert payload["scheduler"] == "error"
    assert payload["status"] == "degraded"
    assert code == 503


def test_health_503_when_telegram_half_open(
    _health_no_io: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        alive_mod,
        "_cb",
        _FakeBreakers(CircuitState.CLOSED, CircuitState.HALF_OPEN),
    )
    payload, code = _call_health()
    assert payload["circuit_telegram"] == "half_open"
    assert payload["status"] == "degraded"
    assert code == 503


def test_index_returns_ok() -> None:
    assert alive_mod.index() == "OK"


def test_webhook_removed_from_alive_module() -> None:
    """The webhook transport is gone; the module exposes no receiver API."""
    assert not hasattr(alive_mod, "webhook_route")
    assert not hasattr(alive_mod, "register_webhook")
    assert not hasattr(alive_mod, "_wh_queue")


def test_start_keepalive_reuses_address(monkeypatch: pytest.MonkeyPatch) -> None:
    """The startup probe matches Werkzeug's SO_REUSEADDR bind behavior."""
    calls: list[object] = []

    class _FakeSocket:
        def setsockopt(self, level: int, optname: int, value: int) -> None:
            calls.append((level, optname, value))

        def bind(self, address: tuple[str, int]) -> None:
            calls.append(("bind", address))

        def close(self) -> None:
            calls.append("close")

    class _FakeThread:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def start(self) -> None:
            calls.append("start")

    monkeypatch.setattr(alive_mod.socket, "socket", lambda *_a: _FakeSocket())
    monkeypatch.setattr(alive_mod.threading, "Thread", _FakeThread)
    monkeypatch.setattr(
        alive_mod, "cfg", SimpleNamespace(bind_host="127.0.0.1", port=5000)
    )

    alive_mod.start_keepalive()

    assert (socket.SOL_SOCKET, socket.SO_REUSEADDR, 1) in calls
    assert ("bind", ("127.0.0.1", 5000)) in calls
    assert "start" in calls
