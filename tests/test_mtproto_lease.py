# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""MTProto single-owner lease: exactly one live client per shared session."""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import time
from types import SimpleNamespace
from typing import Any

import pytest
from pymongo.errors import ConnectionFailure, DuplicateKeyError
from pyrogram.errors import AuthKeyDuplicated
from pyrogram.session.session import AuthKeyNotFound

from tcbot.database import mtproto, mtproto_store
from tcbot.database.mtproto import lifecycle
from tcbot.database.mtproto_store import MongoStorage
from tcbot.utils.circuit_breaker import CircuitOpenError


class _FakeLeaseColl:
    """Minimal Motor collection double supporting exactly the lease operators."""

    def __init__(self) -> None:
        self.docs: dict[str, dict[str, Any]] = {}

    @staticmethod
    def _or_match(doc: dict[str, Any], filt: dict[str, Any]) -> bool:
        for key, cond in filt.items():
            if key == "_id":
                if doc.get("_id") != cond:
                    return False
            elif key == "$or":
                if not any(
                    all(
                        doc.get(k) == v
                        if not isinstance(v, dict)
                        else doc.get(k, 0) < v["$lt"]
                        for k, v in branch.items()
                    )
                    for branch in cond
                ):
                    return False
            elif doc.get(key) != cond:
                return False
        return True

    async def find_one_and_update(
        self,
        filt: dict[str, Any],
        update: dict[str, Any],
        *,
        return_document: object = None,
    ) -> dict[str, Any] | None:
        for doc in self.docs.values():
            if self._or_match(doc, filt):
                doc.update(update.get("$set", {}))
                return dict(doc)
        return None

    async def insert_one(self, doc: dict[str, Any]) -> None:
        if doc["_id"] in self.docs:
            raise DuplicateKeyError("duplicate lease row")
        self.docs[doc["_id"]] = dict(doc)

    async def update_one(
        self, filt: dict[str, Any], update: dict[str, Any]
    ) -> SimpleNamespace:
        for doc in self.docs.values():
            if all(doc.get(k) == v for k, v in filt.items()):
                doc.update(update.get("$set", {}))
                return SimpleNamespace(matched_count=1)
        return SimpleNamespace(matched_count=0)

    async def delete_one(self, filt: dict[str, Any]) -> None:
        for doc_id, doc in list(self.docs.items()):
            if all(doc.get(k) == v for k, v in filt.items()):
                del self.docs[doc_id]
                return


@pytest.fixture
def lease_store(monkeypatch: pytest.MonkeyPatch) -> tuple[MongoStorage, _FakeLeaseColl]:
    """Store wired to the lease fake, with mtproto globals reset."""
    fake = _FakeLeaseColl()
    monkeypatch.setattr(mtproto_store, "col", lambda _name: fake)
    monkeypatch.setattr(mtproto, "_client", None)
    monkeypatch.setattr(mtproto, "_lease_owner", None)
    monkeypatch.setattr(mtproto, "_heartbeat_task", None)
    monkeypatch.setattr(mtproto, "_auth_dead", False)
    return MongoStorage("test-ns"), fake


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


def test_claim_free_lease(lease_store: tuple[MongoStorage, _FakeLeaseColl]) -> None:
    store, fake = lease_store

    assert _run(store.claim_owner("a", ttl_s=90.0)) is True
    assert fake.docs["test-ns:lock:mtproto_owner"]["owner"] == "a"


def test_claim_refused_when_live(
    lease_store: tuple[MongoStorage, _FakeLeaseColl],
) -> None:
    store, fake = lease_store
    fake.docs["test-ns:lock:mtproto_owner"] = {
        "_id": "test-ns:lock:mtproto_owner",
        "owner": "a",
        "expires_at": time.time() + 90.0,
    }

    assert _run(store.claim_owner("b", ttl_s=90.0)) is False
    assert fake.docs["test-ns:lock:mtproto_owner"]["owner"] == "a"


def test_claim_takes_over_expired(
    lease_store: tuple[MongoStorage, _FakeLeaseColl],
) -> None:
    store, fake = lease_store
    fake.docs["test-ns:lock:mtproto_owner"] = {
        "_id": "test-ns:lock:mtproto_owner",
        "owner": "dead",
        "expires_at": time.time() - 1.0,
    }

    assert _run(store.claim_owner("b", ttl_s=90.0)) is True
    assert fake.docs["test-ns:lock:mtproto_owner"]["owner"] == "b"


def test_concurrent_second_claim_loses(
    lease_store: tuple[MongoStorage, _FakeLeaseColl],
) -> None:
    store, _ = lease_store

    assert _run(store.claim_owner("a", ttl_s=90.0)) is True
    assert _run(store.claim_owner("b", ttl_s=90.0)) is False


def test_refresh_renews_and_fences(
    lease_store: tuple[MongoStorage, _FakeLeaseColl],
) -> None:
    store, fake = lease_store
    assert _run(store.claim_owner("a", ttl_s=90.0)) is True

    assert _run(store.refresh_owner("a", ttl_s=90.0)) is True
    assert fake.docs["test-ns:lock:mtproto_owner"]["expires_at"] > time.time()
    assert _run(store.refresh_owner("b", ttl_s=90.0)) is False


def test_release_removes_only_own_row(
    lease_store: tuple[MongoStorage, _FakeLeaseColl],
) -> None:
    store, fake = lease_store
    assert _run(store.claim_owner("a", ttl_s=90.0)) is True

    _run(store.release_owner("b"))
    assert "test-ns:lock:mtproto_owner" in fake.docs
    _run(store.release_owner("a"))
    assert "test-ns:lock:mtproto_owner" not in fake.docs


class _FakeClient:
    """Kurigram client double that never touches the network."""

    def __init__(self, *, connected: bool = False) -> None:
        self.is_connected = connected
        self.start_called = False
        self.stopped = False

    async def start(self) -> None:
        self.start_called = True
        self.is_connected = True

    async def stop(self) -> None:
        self.stopped = True
        self.is_connected = False


def _reset_mtproto_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mtproto, "_client", None)
    monkeypatch.setattr(mtproto, "_lease_owner", None)
    monkeypatch.setattr(mtproto, "_heartbeat_task", None)
    monkeypatch.setattr(mtproto, "_auth_dead", False)
    monkeypatch.setattr(
        mtproto.cfg,
        "_c",
        dataclasses.replace(mtproto.cfg._c, mtproto_session="test-ns"),
    )


def test_start_degraded_when_lease_denied(
    monkeypatch: pytest.MonkeyPatch, lease_store: tuple[MongoStorage, _FakeLeaseColl]
) -> None:
    _reset_mtproto_state(monkeypatch)
    _, fake = lease_store
    fake.docs["test-ns:lock:mtproto_owner"] = {
        "_id": "test-ns:lock:mtproto_owner",
        "owner": "other",
        "expires_at": time.time() + 90.0,
    }
    client = _FakeClient()
    monkeypatch.setattr(mtproto, "_client", client)

    assert asyncio.run(mtproto.start()) is False
    assert client.start_called is False


def test_start_releases_lease_on_connect_failure(
    monkeypatch: pytest.MonkeyPatch, lease_store: tuple[MongoStorage, _FakeLeaseColl]
) -> None:
    _reset_mtproto_state(monkeypatch)
    _, fake = lease_store

    class _Boom(_FakeClient):
        async def start(self) -> None:
            raise RuntimeError("down")

    monkeypatch.setattr(mtproto, "_client", _Boom())

    with pytest.raises(RuntimeError, match="bot session failed"):
        asyncio.run(mtproto.start())
    assert "test-ns:lock:mtproto_owner" not in fake.docs


def test_start_degrades_on_duplicate_key(
    monkeypatch: pytest.MonkeyPatch, lease_store: tuple[MongoStorage, _FakeLeaseColl]
) -> None:
    _reset_mtproto_state(monkeypatch)
    _, fake = lease_store

    class _Dup(_FakeClient):
        async def start(self) -> None:
            raise AuthKeyDuplicated("duplicate")

    client = _Dup()
    monkeypatch.setattr(mtproto, "_client", client)

    assert asyncio.run(mtproto.start()) is False
    assert mtproto.is_auth_dead() is True
    assert client.is_connected is False
    assert "test-ns:lock:mtproto_owner" not in fake.docs
    assert asyncio.run(mtproto.resolve_user(42)) is None


def test_start_degrades_on_not_found_key(
    monkeypatch: pytest.MonkeyPatch, lease_store: tuple[MongoStorage, _FakeLeaseColl]
) -> None:
    _reset_mtproto_state(monkeypatch)
    _, fake = lease_store

    class _Gone(_FakeClient):
        async def start(self) -> None:
            raise AuthKeyNotFound("gone")

    client = _Gone()
    monkeypatch.setattr(mtproto, "_client", client)

    assert asyncio.run(mtproto.start()) is False
    assert mtproto.is_auth_dead() is True
    assert client.is_connected is False
    assert "test-ns:lock:mtproto_owner" not in fake.docs
    assert asyncio.run(mtproto.resolve_user(42)) is None


def test_handle_auth_failure_parks_once(
    monkeypatch: pytest.MonkeyPatch, lease_store: tuple[MongoStorage, _FakeLeaseColl]
) -> None:
    _reset_mtproto_state(monkeypatch)
    _, fake = lease_store
    client = _FakeClient(connected=True)
    monkeypatch.setattr(mtproto, "_client", client)
    monkeypatch.setattr(mtproto, "_lease_owner", "me")
    fake.docs["test-ns:lock:mtproto_owner"] = {
        "_id": "test-ns:lock:mtproto_owner",
        "owner": "me",
        "expires_at": time.time() + 90.0,
    }

    asyncio.run(mtproto.handle_auth_failure())
    asyncio.run(mtproto.handle_auth_failure())

    assert mtproto.is_auth_dead() is True
    assert client.stopped is True
    assert mtproto._client is None
    assert "test-ns:lock:mtproto_owner" not in fake.docs
    assert asyncio.run(mtproto.resolve_user(42)) is None


def test_is_auth_key_duplicated() -> None:
    assert mtproto.is_auth_key_duplicated(AuthKeyDuplicated("x")) is True
    assert mtproto.is_auth_key_duplicated(RuntimeError("x")) is False


def test_is_auth_key_not_found() -> None:
    assert mtproto.is_auth_key_not_found(AuthKeyNotFound("x")) is True
    assert mtproto.is_auth_key_not_found(RuntimeError("x")) is False
    assert mtproto.is_auth_key_not_found(AuthKeyDuplicated("x")) is False


def test_claim_outage_returns_false(
    monkeypatch: pytest.MonkeyPatch, lease_store: tuple[MongoStorage, _FakeLeaseColl]
) -> None:
    """A MongoDB outage on claim refuses instead of reporting a held lease."""
    store, _ = lease_store

    async def _boom(_coro: object) -> Any:
        close = getattr(_coro, "close", None)
        if callable(close):
            close()
        raise ConnectionFailure("no primary")

    monkeypatch.setattr(
        "tcbot.database.mtproto_store.lease.db_call",
        _boom,
    )
    assert _run(store.claim_owner("a", ttl_s=90.0)) is False


def test_claim_circuit_open_returns_false(
    monkeypatch: pytest.MonkeyPatch, lease_store: tuple[MongoStorage, _FakeLeaseColl]
) -> None:
    """An open circuit on claim also refuses instead of falling through."""
    store, _ = lease_store

    async def _boom(_coro: object) -> Any:
        close = getattr(_coro, "close", None)
        if callable(close):
            close()
        raise CircuitOpenError("Circuit [mongodb] is OPEN; call rejected.")

    monkeypatch.setattr(
        "tcbot.database.mtproto_store.lease.db_call",
        _boom,
    )
    assert _run(store.claim_owner("a", ttl_s=90.0)) is False


def test_heartbeat_defers_on_connection_failure(
    monkeypatch: pytest.MonkeyPatch, caplog: Any
) -> None:
    """Expected outage beats warn without a traceback and keep the loop alive."""
    calls = 0

    class _Store:
        async def refresh_owner(self, owner: str, *, ttl_s: float) -> bool:
            nonlocal calls
            calls += 1
            if calls == 1:
                raise ConnectionFailure("no primary")
            return True

    monkeypatch.setattr(lifecycle._mtproto_pkg, "_HEARTBEAT_S", 0.0)

    class _Client:
        pass

    with caplog.at_level(0):

        async def _do() -> None:
            task = asyncio.create_task(
                lifecycle._heartbeat_lease(_Client(), _Store(), "owner")  # type: ignore[arg-type]
            )
            await asyncio.sleep(0.05)
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

        asyncio.run(_do())
    assert calls >= 2
    assert "MTProto lease heartbeat deferred" in caplog.text
    assert "Traceback" not in caplog.text


def test_heartbeat_defers_on_circuit_open(
    monkeypatch: pytest.MonkeyPatch, caplog: Any
) -> None:
    """Circuit-open beats share the quiet deferral path."""
    calls = 0

    class _Store:
        async def refresh_owner(self, owner: str, *, ttl_s: float) -> bool:
            nonlocal calls
            calls += 1
            if calls == 1:
                raise CircuitOpenError("Circuit [mongodb] is OPEN; call rejected.")
            return True

    monkeypatch.setattr(lifecycle._mtproto_pkg, "_HEARTBEAT_S", 0.0)

    class _Client:
        pass

    with caplog.at_level(0):

        async def _do() -> None:
            task = asyncio.create_task(
                lifecycle._heartbeat_lease(_Client(), _Store(), "owner")  # type: ignore[arg-type]
            )
            await asyncio.sleep(0.05)
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

        asyncio.run(_do())
    assert calls >= 2
    assert "MTProto lease heartbeat deferred" in caplog.text
    assert "Traceback" not in caplog.text
