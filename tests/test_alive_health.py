# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Health endpoint: mongodb verdict requires a fully CLOSED circuit."""

from __future__ import annotations

import concurrent.futures
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

import tcbot.alive as alive_mod
from tcbot.utils.circuit_breaker import CircuitBreaker, CircuitState
from tcbot.utils.time_and_date import monotonic


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


def test_health_never_flips_telegram_circuit(
    _health_no_io: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    overdue: Any = CircuitBreaker("telegram", recovery_timeout=60.0)
    overdue._state = CircuitState.OPEN
    overdue._opened_at = monotonic() - 3600.0

    monkeypatch.setattr(
        alive_mod,
        "_cb",
        SimpleNamespace(mongodb=_FakeCircuit(CircuitState.CLOSED), telegram=overdue),
    )
    payload, code = _call_health()

    assert overdue.peek_state() is CircuitState.OPEN
    assert payload["circuit_telegram"] == "open"
    assert payload["status"] == "degraded"
    assert code == 503


_WH_SECRET = "hook-secret"


class _FakePutCoro:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class _FakeWhQueue:
    def __init__(self, *, qsize_val: int = 0, put_exc: Exception | None = None) -> None:
        self._qsize_val = qsize_val
        self._put_exc = put_exc
        self.put_item: object | None = None
        self.last_coro: _FakePutCoro | None = None

    def qsize(self) -> int:
        return self._qsize_val

    def put(self, item: object) -> _FakePutCoro:
        if self._put_exc is not None:
            raise self._put_exc
        self.put_item = item
        self.last_coro = _FakePutCoro()
        return self.last_coro


class _FakeFuture:
    def __init__(self, *, exc: Exception | None = None) -> None:
        self._exc = exc
        self.cancelled = False

    def result(self, timeout: float | None = None) -> None:
        if self._exc is not None:
            raise self._exc

    def cancel(self) -> bool:
        self.cancelled = True
        return True


def _wire_webhook(
    monkeypatch: pytest.MonkeyPatch,
    *,
    queue: Any,
    loop: Any,
    bot: Any,
    secret: str = _WH_SECRET,
) -> None:
    monkeypatch.setattr(alive_mod, "_wh_queue", queue)
    monkeypatch.setattr(alive_mod, "_wh_loop", loop)
    monkeypatch.setattr(alive_mod, "_wh_bot", bot)
    monkeypatch.setattr(alive_mod, "_wh_secret", secret)


def _call_webhook(
    *,
    json_data: dict[str, Any] | None = None,
    token: str | None = _WH_SECRET,
) -> tuple[str, int]:
    headers: dict[str, str] = {}
    if token is not None:
        headers["X-Telegram-Bot-Api-Secret-Token"] = token
    kwargs: dict[str, Any] = {"method": "POST", "headers": headers}
    if json_data is not None:
        kwargs["json"] = json_data
    with alive_mod._app.test_request_context("/webhook", **kwargs):
        return alive_mod.webhook_route()


def _stub_de_json(
    monkeypatch: pytest.MonkeyPatch,
    *,
    ret: Any = None,
    exc: Exception | None = None,
) -> None:
    if exc is not None:

        def _raise(data: dict[str, Any], bot: Any = None) -> Any:
            raise exc

        monkeypatch.setattr(alive_mod, "Update", SimpleNamespace(de_json=_raise))
    else:
        monkeypatch.setattr(
            alive_mod,
            "Update",
            SimpleNamespace(de_json=lambda data, bot=None: ret),
        )


def test_health_update_queue_none_when_unwired(
    _health_no_io: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(alive_mod, "_wh_queue", None)
    payload, code = _call_health()
    assert payload["update_queue"] is None
    assert code == 200


def test_health_update_queue_qsize_when_wired(
    _health_no_io: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(alive_mod, "_wh_queue", _FakeWhQueue(qsize_val=7))
    payload, code = _call_health()
    assert payload["update_queue"] == 7
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


def test_webhook_403_when_secret_wrong(monkeypatch: pytest.MonkeyPatch) -> None:
    _wire_webhook(monkeypatch, queue=_FakeWhQueue(), loop=object(), bot=object())
    body, code = _call_webhook(json_data={"update_id": 1}, token="wrong")
    assert code == 403
    assert body == "Forbidden"


def test_webhook_403_when_secret_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    _wire_webhook(monkeypatch, queue=_FakeWhQueue(), loop=object(), bot=object())
    body, code = _call_webhook(json_data={"update_id": 1}, token=None)
    assert code == 403
    assert body == "Forbidden"


def test_webhook_503_when_ptb_not_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    _wire_webhook(monkeypatch, queue=None, loop=None, bot=None)
    body, code = _call_webhook(json_data={"update_id": 1})
    assert code == 503
    assert body == "Service unavailable"


def test_webhook_400_when_empty_body(monkeypatch: pytest.MonkeyPatch) -> None:
    _wire_webhook(monkeypatch, queue=_FakeWhQueue(), loop=object(), bot=object())
    body, code = _call_webhook()
    assert code == 400
    assert body == "Bad request"


def test_webhook_400_when_decode_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    _wire_webhook(monkeypatch, queue=_FakeWhQueue(), loop=object(), bot=object())
    _stub_de_json(monkeypatch, exc=ValueError("bad payload"))
    body, code = _call_webhook(json_data={"update_id": 1})
    assert code == 400
    assert body == "Bad request"


def test_webhook_200_ack_when_update_none(monkeypatch: pytest.MonkeyPatch) -> None:
    _wire_webhook(monkeypatch, queue=_FakeWhQueue(), loop=object(), bot=object())
    _stub_de_json(monkeypatch, ret=None)
    body, code = _call_webhook(json_data={"update_id": 1})
    assert code == 200
    assert body == "OK"


def test_webhook_200_when_enqueue_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue = _FakeWhQueue()
    _wire_webhook(monkeypatch, queue=queue, loop=object(), bot=object())
    sentinel = object()
    _stub_de_json(monkeypatch, ret=sentinel)
    monkeypatch.setattr(
        alive_mod.asyncio,
        "run_coroutine_threadsafe",
        lambda coro, loop: _FakeFuture(),
    )
    body, code = _call_webhook(json_data={"update_id": 1})
    assert code == 200
    assert body == "OK"
    assert queue.put_item is sentinel


def test_webhook_503_when_loop_rejects(monkeypatch: pytest.MonkeyPatch) -> None:
    queue = _FakeWhQueue()
    _wire_webhook(monkeypatch, queue=queue, loop=object(), bot=object())
    _stub_de_json(monkeypatch, ret=object())

    def _raise(coro: Any, loop: Any) -> Any:
        raise RuntimeError("loop closed")

    monkeypatch.setattr(alive_mod.asyncio, "run_coroutine_threadsafe", _raise)
    body, code = _call_webhook(json_data={"update_id": 1})
    assert code == 503
    assert body == "Service unavailable"
    assert queue.last_coro is not None
    assert queue.last_coro.closed is True


def test_webhook_503_when_enqueue_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    _wire_webhook(monkeypatch, queue=_FakeWhQueue(), loop=object(), bot=object())
    _stub_de_json(monkeypatch, ret=object())
    monkeypatch.setattr(
        alive_mod.asyncio,
        "run_coroutine_threadsafe",
        lambda coro, loop: _FakeFuture(exc=concurrent.futures.TimeoutError("slow")),
    )
    body, code = _call_webhook(json_data={"update_id": 1})
    assert code == 503
    assert body == "Service unavailable"


def test_webhook_503_when_future_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _wire_webhook(monkeypatch, queue=_FakeWhQueue(), loop=object(), bot=object())
    _stub_de_json(monkeypatch, ret=object())
    monkeypatch.setattr(
        alive_mod.asyncio,
        "run_coroutine_threadsafe",
        lambda coro, loop: _FakeFuture(exc=RuntimeError("queue full")),
    )
    body, code = _call_webhook(json_data={"update_id": 1})
    assert code == 503
    assert body == "Service unavailable"


def test_webhook_500_when_queue_put_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _wire_webhook(
        monkeypatch,
        queue=_FakeWhQueue(put_exc=RuntimeError("broken")),
        loop=object(),
        bot=object(),
    )
    _stub_de_json(monkeypatch, ret=object())
    body, code = _call_webhook(json_data={"update_id": 1})
    assert code == 500
    assert body == "Internal error"
