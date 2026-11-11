# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""MTProto single-owner lease: exactly one live client per shared session."""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
from typing import TYPE_CHECKING, Any

import pytest
from pyrogram.errors import AuthKeyDuplicated
from pyrogram.session.session import AuthKeyNotFound
from sqlalchemy.exc import OperationalError

from tcbot.database import mtproto, mtproto_store
from tcbot.database.mtproto_store import PostgresStorage
from tcbot.utils.circuit_breaker import CircuitOpenError
from tests.postgres_support import compile_sql, identity_db_call

if TYPE_CHECKING:
    from collections.abc import Awaitable

# * The lease row lives in the session table under this id.
_LEASE_ID: str = "test-ns:lock:mtproto_owner"


class _FakeDriverError(Exception):
    """Driver error double carrying the SQLSTATE the classifier reads."""

    def __init__(self, sqlstate: str) -> None:
        super().__init__(f"driver error {sqlstate}")
        self.sqlstate = sqlstate


class _Recorder:
    """Captures the lease statements and replays canned results."""

    def __init__(self, results: list[Any] | None = None) -> None:
        self.statements: list[Any] = []
        self.results: list[Any] = list(results or [])
        self.affected: int = 0

    async def run_returning(self, stmt: Any) -> list[dict[str, Any]]:
        self.statements.append(stmt)
        if self.results:
            return self.results.pop(0)
        return []

    async def run(self, stmt: Any) -> int:
        self.statements.append(stmt)
        return self.affected


class _LeaseSpy:
    """Records the lease calls the client lifecycle makes."""

    def __init__(self, *, claimed: bool = True) -> None:
        self.claimed = claimed
        self.claims: list[str] = []
        self.releases: list[str] = []

    async def claim(self, _store: Any, owner: str, *, ttl_s: float) -> bool:
        _ = ttl_s
        self.claims.append(owner)
        return self.claimed

    async def release(self, _store: Any, owner: str) -> None:
        self.releases.append(owner)


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
        mtproto,
        "cfg",
        dataclasses.replace(mtproto.cfg, mtproto_session="test-ns"),
    )


def _stub_lease(monkeypatch: pytest.MonkeyPatch, spy: _LeaseSpy) -> None:
    """Stub the owner lease so start()/stop() never touch the database."""

    async def _claim(self: Any, owner: str, *, ttl_s: float) -> bool:
        return await spy.claim(self, owner, ttl_s=ttl_s)

    async def _release(self: Any, owner: str) -> None:
        await spy.release(self, owner)

    monkeypatch.setattr(PostgresStorage, "claim_owner", _claim)
    monkeypatch.setattr(PostgresStorage, "release_owner", _release)


def _run(coro: Awaitable[Any]) -> Any:
    return asyncio.run(coro)


# ─────────────────────────── Claim ──────────────────────────────── #


def test_the_lease_row_id_is_namespaced() -> None:
    """The lease lives in the session table under a namespaced id."""
    store = PostgresStorage("test-ns")

    assert store._lease_id() == _LEASE_ID


def test_the_claim_is_a_single_atomic_update(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The takeover is one statement with the owner and the expiry predicate."""
    rec = _Recorder([[{"id": _LEASE_ID}]])
    monkeypatch.setattr(mtproto_store, "db_call", identity_db_call)
    monkeypatch.setattr(mtproto_store, "run_returning", rec.run_returning)

    claimed = _run(
        mtproto_store.claim_owner(PostgresStorage("test-ns"), "a", ttl_s=90.0)
    )

    assert claimed is True
    assert len(rec.statements) == 1
    sql = compile_sql(rec.statements[0])
    assert sql.startswith("UPDATE mtproto_state SET owner=")
    assert "mtproto_state.owner = " in sql
    assert "mtproto_state.expires_at <" in sql
    assert "RETURNING mtproto_state.id" in sql


def test_the_claim_inserts_the_lease_on_the_first_boot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The first boot inserts the lease row and skips a lost insert race."""
    rec = _Recorder([[], [{"id": _LEASE_ID}]])
    monkeypatch.setattr(mtproto_store, "db_call", identity_db_call)
    monkeypatch.setattr(mtproto_store, "run_returning", rec.run_returning)

    claimed = _run(
        mtproto_store.claim_owner(PostgresStorage("test-ns"), "a", ttl_s=90.0)
    )

    assert claimed is True
    assert len(rec.statements) == 2
    sql = compile_sql(rec.statements[1])
    assert sql.startswith("INSERT INTO mtproto_state")
    assert "ON CONFLICT (id) DO NOTHING" in sql


def test_the_claim_refuses_a_live_foreign_lease(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A live lease held by anyone else refuses the claim."""
    rec = _Recorder([[], []])
    monkeypatch.setattr(mtproto_store, "db_call", identity_db_call)
    monkeypatch.setattr(mtproto_store, "run_returning", rec.run_returning)

    claimed = _run(
        mtproto_store.claim_owner(PostgresStorage("test-ns"), "b", ttl_s=90.0)
    )

    assert claimed is False
    # * The insert cannot take over a lease row that already exists.
    assert "ON CONFLICT (id) DO NOTHING" in compile_sql(rec.statements[1])


def test_the_concurrent_second_claim_loses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two claimants can never both hold the lease."""
    rec = _Recorder([[{"id": _LEASE_ID}], [], []])
    monkeypatch.setattr(mtproto_store, "db_call", identity_db_call)
    monkeypatch.setattr(mtproto_store, "run_returning", rec.run_returning)
    store = PostgresStorage("test-ns")

    assert _run(mtproto_store.claim_owner(store, "a", ttl_s=90.0)) is True
    assert _run(mtproto_store.claim_owner(store, "b", ttl_s=90.0)) is False


def test_the_refresh_fences_the_other_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only the holder can renew the lease."""
    rec = _Recorder()
    rec.affected = 1
    monkeypatch.setattr(mtproto_store, "db_call", identity_db_call)
    monkeypatch.setattr(mtproto_store, "run", rec.run)

    held = _run(
        mtproto_store.refresh_owner(PostgresStorage("test-ns"), "a", ttl_s=90.0)
    )

    assert held is True
    sql = compile_sql(rec.statements[0])
    assert "mtproto_state.owner = " in sql
    assert "expires_at=" in sql


def test_the_release_removes_only_its_own_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A release never removes the lease of another holder."""
    rec = _Recorder()
    monkeypatch.setattr(mtproto_store, "db_call", identity_db_call)
    monkeypatch.setattr(mtproto_store, "run", rec.run)

    _run(mtproto_store.release_owner(PostgresStorage("test-ns"), "b"))

    sql = compile_sql(rec.statements[0])
    assert "DELETE FROM mtproto_state" in sql
    assert "mtproto_state.owner = " in sql


def test_the_claim_refuses_on_a_database_outage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A database outage on claim refuses instead of reporting a held lease."""

    async def _boom(_op: Any, **_kwargs: Any) -> Any:
        raise OperationalError("stmt", {}, _FakeDriverError("08006"))

    monkeypatch.setattr(mtproto_store, "db_call", _boom)

    claimed = _run(
        mtproto_store.claim_owner(PostgresStorage("test-ns"), "a", ttl_s=90.0)
    )

    assert claimed is False


def test_the_claim_refuses_when_the_circuit_is_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An open circuit on claim also refuses instead of falling through."""

    async def _boom(_op: Any, **_kwargs: Any) -> Any:
        raise CircuitOpenError("Circuit [postgres] is OPEN; call rejected.")

    monkeypatch.setattr(mtproto_store, "db_call", _boom)

    claimed = _run(
        mtproto_store.claim_owner(PostgresStorage("test-ns"), "a", ttl_s=90.0)
    )

    assert claimed is False


# ─────────────────────── Client lifecycle ───────────────────────── #


def test_start_degrades_when_the_lease_is_denied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without the lease the bot runs Bot-API-only and connects nothing."""
    _reset_mtproto_state(monkeypatch)
    spy = _LeaseSpy(claimed=False)
    _stub_lease(monkeypatch, spy)
    client = _FakeClient()
    monkeypatch.setattr(mtproto, "_client", client)

    assert asyncio.run(mtproto.start()) is False
    assert client.start_called is False


def test_start_releases_the_lease_on_connect_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed login hands the lease back instead of holding it."""
    _reset_mtproto_state(monkeypatch)
    spy = _LeaseSpy()
    _stub_lease(monkeypatch, spy)

    class _Boom(_FakeClient):
        async def start(self) -> None:
            raise RuntimeError("down")

    monkeypatch.setattr(mtproto, "_client", _Boom())

    with pytest.raises(RuntimeError, match="bot session failed"):
        asyncio.run(mtproto.start())
    assert len(spy.releases) == 1


def test_start_degrades_on_duplicate_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A duplicated auth key parks the session instead of crashing the bot."""
    _reset_mtproto_state(monkeypatch)
    spy = _LeaseSpy()
    _stub_lease(monkeypatch, spy)

    class _Dup(_FakeClient):
        async def start(self) -> None:
            raise AuthKeyDuplicated("duplicate")

    client = _Dup()
    monkeypatch.setattr(mtproto, "_client", client)

    assert asyncio.run(mtproto.start()) is False
    assert mtproto.is_auth_dead() is True
    assert client.is_connected is False
    assert len(spy.releases) == 1
    assert asyncio.run(mtproto.resolve_user(42)) is None


def test_start_degrades_on_not_found_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A vanished auth key parks the session instead of crashing the bot."""
    _reset_mtproto_state(monkeypatch)
    spy = _LeaseSpy()
    _stub_lease(monkeypatch, spy)

    class _Gone(_FakeClient):
        async def start(self) -> None:
            raise AuthKeyNotFound("gone")

    client = _Gone()
    monkeypatch.setattr(mtproto, "_client", client)

    assert asyncio.run(mtproto.start()) is False
    assert mtproto.is_auth_dead() is True
    assert client.is_connected is False
    assert len(spy.releases) == 1
    assert asyncio.run(mtproto.resolve_user(42)) is None


def test_handle_auth_failure_parks_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The park is idempotent: the lease is released exactly once."""
    _reset_mtproto_state(monkeypatch)
    spy = _LeaseSpy()
    _stub_lease(monkeypatch, spy)
    client = _FakeClient(connected=True)
    monkeypatch.setattr(mtproto, "_client", client)
    monkeypatch.setattr(mtproto, "_lease_owner", "me")

    asyncio.run(mtproto.handle_auth_failure())
    asyncio.run(mtproto.handle_auth_failure())

    assert mtproto.is_auth_dead() is True
    assert client.stopped is True
    assert mtproto._client is None
    assert len(spy.releases) == 1
    assert asyncio.run(mtproto.resolve_user(42)) is None


def test_is_auth_key_duplicated() -> None:
    assert mtproto.is_auth_key_duplicated(AuthKeyDuplicated("x")) is True
    assert mtproto.is_auth_key_duplicated(RuntimeError("x")) is False


def test_is_auth_key_not_found() -> None:
    assert mtproto.is_auth_key_not_found(AuthKeyNotFound("x")) is True
    assert mtproto.is_auth_key_not_found(RuntimeError("x")) is False
    assert mtproto.is_auth_key_not_found(AuthKeyDuplicated("x")) is False


# ─────────────────────────── Heartbeat ───────────────────────────── #


def test_the_heartbeat_defers_quietly_on_circuit_open(
    monkeypatch: pytest.MonkeyPatch, caplog: Any
) -> None:
    """An open circuit beats warn without a traceback and keeps the loop alive."""
    calls = 0

    class _Store:
        async def refresh_owner(self, owner: str, *, ttl_s: float) -> bool:
            nonlocal calls
            _ = (owner, ttl_s)
            calls += 1
            if calls == 1:
                raise CircuitOpenError("Circuit [postgres] is OPEN; call rejected.")
            return True

    monkeypatch.setattr(mtproto, "_HEARTBEAT_S", 0.0)

    class _Client:
        pass

    with caplog.at_level(0):

        async def _do() -> None:
            task = asyncio.create_task(
                mtproto._heartbeat_lease(_Client(), _Store(), "owner")  # type: ignore[arg-type]
            )
            await asyncio.sleep(0.05)
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

        asyncio.run(_do())
    assert calls >= 2
    assert "MTProto lease heartbeat deferred" in caplog.text
    assert "Traceback" not in caplog.text


def test_the_heartbeat_retries_after_a_database_failure(
    monkeypatch: pytest.MonkeyPatch, caplog: Any
) -> None:
    """A database outage is logged and the loop keeps beating.

    The lease is not lost by an outage: only a refresh that reports the
    lease as gone fences the client out.
    """
    calls = 0

    class _Store:
        async def refresh_owner(self, owner: str, *, ttl_s: float) -> bool:
            nonlocal calls
            _ = (owner, ttl_s)
            calls += 1
            if calls == 1:
                raise OperationalError("stmt", {}, _FakeDriverError("08006"))
            return True

    monkeypatch.setattr(mtproto, "_HEARTBEAT_S", 0.0)

    class _Client:
        def __init__(self) -> None:
            self.stopped = False

        async def stop(self) -> None:
            self.stopped = True

    client = _Client()

    with caplog.at_level(0):

        async def _do() -> None:
            task = asyncio.create_task(
                mtproto._heartbeat_lease(client, _Store(), "owner")  # type: ignore[arg-type]
            )
            await asyncio.sleep(0.05)
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

        asyncio.run(_do())
    assert calls >= 2
    assert "MTProto lease heartbeat failed" in caplog.text
    assert client.stopped is False
