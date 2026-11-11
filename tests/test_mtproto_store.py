# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""PostgresStorage: the SQL contract of the store and the write retry policy."""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any

import msgspec
import pytest
from pyrogram.storage import UpdateState
from sqlalchemy.exc import IntegrityError, InterfaceError, OperationalError

from tcbot.database import engine as engine_module
from tcbot.database import mtproto_store
from tcbot.database.base import mtproto_state
from tcbot.database.mtproto_store import PostgresStorage
from tcbot.utils.circuit_breaker import CircuitOpenError
from tests.postgres_support import compile_sql, identity_db_call, stmt_params

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


class _FakeDriverError(Exception):
    """Driver error double carrying the SQLSTATE the classifier reads."""

    def __init__(self, sqlstate: str) -> None:
        super().__init__(f"driver error {sqlstate}")
        self.sqlstate = sqlstate


class _Recorder:
    """Captures the statements the storage engine sends to the database."""

    def __init__(self) -> None:
        self.statements: list[Any] = []
        self.rows: list[dict[str, Any]] = []
        self.affected: int = 0

    async def run(self, stmt: Any) -> int:
        self.statements.append(stmt)
        return self.affected

    async def run_returning(self, stmt: Any) -> list[dict[str, Any]]:
        self.statements.append(stmt)
        return self.rows

    async def fetch_one(self, stmt: Any) -> dict[str, Any] | None:
        self.statements.append(stmt)
        return self.rows[0] if self.rows else None

    async def fetch_all(self, stmt: Any) -> list[dict[str, Any]]:
        self.statements.append(stmt)
        return self.rows


@pytest.fixture
def recorder(monkeypatch: pytest.MonkeyPatch) -> _Recorder:
    """Patch the store transport so every statement is recorded, not executed."""
    rec = _Recorder()
    monkeypatch.setattr(mtproto_store, "db_call", identity_db_call)
    monkeypatch.setattr(mtproto_store, "run", rec.run)
    monkeypatch.setattr(mtproto_store, "run_returning", rec.run_returning)
    monkeypatch.setattr(mtproto_store, "fetch_one", rec.fetch_one)
    monkeypatch.setattr(mtproto_store, "fetch_all", rec.fetch_all)
    return rec


@pytest.fixture
def store() -> PostgresStorage:
    """Return a store scoped to the test namespace."""
    return PostgresStorage("test")


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


# ────────────────────────────── Keys ────────────────────────────── #


def test_the_row_ids_are_namespaced(store: PostgresStorage) -> None:
    """Every key of the session carries the namespace."""
    assert store._kv("auth_key") == "test:kv:auth_key"
    assert store._peer(42) == "test:peer:42"
    assert store._ustate(7) == "test:ustate:7"
    assert store._lease_id() == "test:lock:mtproto_owner"


# ───────────────────────────── Scalars ──────────────────────────── #


def test_a_scalar_is_stored_as_msgpack(
    store: PostgresStorage, recorder: _Recorder
) -> None:
    """The opaque session payload travels as msgpack in the value column."""
    _run(store.auth_key(b"\x01\x02"))

    params = stmt_params(recorder.statements[0])
    assert params["id"] == "test:kv:auth_key"
    assert params["value"] == msgspec.msgpack.encode(b"\x01\x02")


def test_a_scalar_write_upserts_on_the_row_id(
    store: PostgresStorage, recorder: _Recorder
) -> None:
    """The write never creates a second row for the same key."""
    _run(store.user_id(7))

    sql = compile_sql(recorder.statements[0])
    assert sql.startswith("INSERT INTO mtproto_state")
    assert "ON CONFLICT (id) DO UPDATE" in sql


def test_reading_a_scalar_selects_the_value_column(
    store: PostgresStorage, recorder: _Recorder
) -> None:
    """The read targets the namespaced key row."""
    _run(store.auth_key())

    sql = compile_sql(recorder.statements[0])
    assert "FROM mtproto_state" in sql
    assert "mtproto_state.value" in sql
    params = stmt_params(recorder.statements[0])
    assert params["id_1"] == "test:kv:auth_key"


def test_a_missing_scalar_reads_none(
    store: PostgresStorage, recorder: _Recorder
) -> None:
    """A key that was never written reads as None."""
    recorder.rows = []

    assert _run(store.dc_id()) is None


# ────────────────────────────── Peers ───────────────────────────── #


def test_update_peers_upserts_the_peer_row(
    store: PostgresStorage, recorder: _Recorder
) -> None:
    """The peer row carries the access hash, the type and the phone number."""
    _run(store.update_peers([(42, 99, "user", "+15550000")]))

    params = stmt_params(recorder.statements[0])
    assert params["id"] == "test:peer:42"
    assert params["access_hash"] == 99
    assert params["type"] == "user"
    assert params["phone_number"] == "+15550000"
    sql = compile_sql(recorder.statements[0])
    assert "ON CONFLICT (id) DO UPDATE" in sql


def test_update_usernames_replaces_the_name_list(
    store: PostgresStorage, recorder: _Recorder
) -> None:
    """A names-only write keeps the stored access hash and peer type."""
    _run(store.update_usernames([(42, ["ghost", None])]))

    params = stmt_params(recorder.statements[0])
    assert params["id"] == "test:peer:42"
    assert list(params["usernames"]) == ["ghost"]
    sql = compile_sql(recorder.statements[0])
    assert "usernames" in sql
    assert "updated_on" in sql
    assert "access_hash" not in sql


def test_the_peer_lookup_selects_the_peer_columns(
    store: PostgresStorage, recorder: _Recorder
) -> None:
    """The peer read asks for the access hash and the peer type."""
    recorder.rows = [{"access_hash": 99, "type": "user"}]

    peer = _run(store.get_peer_by_id(42))

    assert peer.user_id == 42
    assert peer.access_hash == 99
    sql = compile_sql(recorder.statements[0])
    assert "mtproto_state.access_hash" in sql
    assert "mtproto_state.type" in sql


def test_a_missing_peer_raises_keyerror(
    store: PostgresStorage, recorder: _Recorder
) -> None:
    """An unknown peer is a miss, exactly like the SQLite storage."""
    recorder.rows = []

    with pytest.raises(KeyError):
        _run(store.get_peer_by_id(1))


def test_a_peer_without_an_access_hash_is_a_miss(
    store: PostgresStorage, recorder: _Recorder
) -> None:
    """A peer row that cannot address Telegram is reported as a miss."""
    recorder.rows = [{"access_hash": None, "type": "user"}]

    with pytest.raises(KeyError):
        _run(store.get_peer_by_id(1))


def test_the_username_lookup_uses_the_containment_operator(
    store: PostgresStorage, recorder: _Recorder
) -> None:
    """The name lookup uses the operator the GIN index can serve."""
    recorder.rows = [
        {
            "id": "test:peer:42",
            "access_hash": 99,
            "type": "user",
            "updated_on": int(time.time()),
        }
    ]

    peer = _run(store.get_peer_by_username("ghost"))

    assert peer.user_id == 42
    sql = compile_sql(recorder.statements[0])
    assert "mtproto_state.usernames @>" in sql
    assert "ORDER BY mtproto_state.updated_on DESC" in sql
    assert "LIMIT" in sql


def test_a_missing_username_raises_keyerror(
    store: PostgresStorage, recorder: _Recorder
) -> None:
    """An unknown username is a miss."""
    recorder.rows = []

    with pytest.raises(KeyError):
        _run(store.get_peer_by_username("nobody"))


def test_an_expired_username_raises_keyerror(
    store: PostgresStorage, recorder: _Recorder
) -> None:
    """A stale name list is a miss, exactly like the SQLite storage."""
    recorder.rows = [
        {
            "id": "test:peer:42",
            "access_hash": 99,
            "type": "user",
            "updated_on": int(time.time()) - 10 * 60 * 60,
        }
    ]

    with pytest.raises(KeyError):
        _run(store.get_peer_by_username("ghost"))


def test_the_phone_lookup_filters_on_the_number(
    store: PostgresStorage, recorder: _Recorder
) -> None:
    """The phone lookup asks for the stored number."""
    recorder.rows = [
        {
            "id": "test:peer:42",
            "access_hash": 99,
            "type": "user",
        }
    ]

    peer = _run(store.get_peer_by_phone_number("+15550000"))

    assert peer.user_id == 42
    sql = compile_sql(recorder.statements[0])
    assert "mtproto_state.phone_number = " in sql


# ─────────────────────────── Update states ───────────────────────── #


def test_an_update_state_only_writes_the_known_fields(
    store: PostgresStorage, recorder: _Recorder
) -> None:
    """A field the caller did not know keeps its stored value."""
    _run(store.set_update_state(UpdateState(0, 10, None, 5, 1)))

    params = stmt_params(recorder.statements[0])
    assert params["id"] == "test:ustate:0"
    assert params["pts"] == 10
    assert params["date"] == 5
    assert params["seq"] == 1
    assert "qts" not in params


def test_the_update_states_are_read_oldest_first(
    store: PostgresStorage, recorder: _Recorder
) -> None:
    """The session worker reads the update states oldest first."""
    recorder.rows = [
        {
            "id": "test:ustate:0",
            "pts": 10,
            "qts": 20,
            "date": 5,
            "seq": 1,
        }
    ]

    (merged,) = _run(store.get_update_states(0))

    assert (merged.pts, merged.qts, merged.date, merged.seq) == (10, 20, 5, 1)
    sql = compile_sql(recorder.statements[0])
    assert "ORDER BY mtproto_state.date ASC" in sql


def test_deleting_an_update_state_targets_its_namespaced_id(
    store: PostgresStorage, recorder: _Recorder
) -> None:
    """The delete cannot reach another namespace."""
    _run(store.delete_update_state(0))

    sql = compile_sql(recorder.statements[0])
    assert "DELETE FROM mtproto_state" in sql
    params = stmt_params(recorder.statements[0])
    assert list(params["id_1"]) == ["test:ustate:0"]


def test_deleting_the_session_only_removes_its_own_namespace(
    store: PostgresStorage, recorder: _Recorder
) -> None:
    """A namespace never touches the rows of another session."""
    _run(store.delete())

    sql = compile_sql(recorder.statements[0])
    assert "DELETE FROM mtproto_state" in sql
    params = stmt_params(recorder.statements[0])
    assert params["id_1"] == "test:%"


# ──────────────────────────── Write retry ────────────────────────── #


def test_retry_write_succeeds_after_transient_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A serialization failure retries and succeeds."""
    monkeypatch.setattr(mtproto_store, "db_call", identity_db_call)
    monkeypatch.setattr(mtproto_store, "_RETRY_BASE_DELAY", 0.0)
    calls = 0

    async def _run_test() -> str:
        nonlocal calls

        async def _failing_coro() -> str:
            nonlocal calls
            calls += 1
            if calls < 3:
                raise OperationalError("stmt", {}, _FakeDriverError("40001"))
            return "ok"

        return await mtproto_store._retry_write(_failing_coro)

    assert asyncio.run(_run_test()) == "ok"
    assert calls == 3


def test_retry_write_degrades_after_max_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An exhausted retry budget degrades to None instead of raising."""
    monkeypatch.setattr(mtproto_store, "db_call", identity_db_call)
    monkeypatch.setattr(mtproto_store, "_RETRY_BASE_DELAY", 0.0)
    calls = 0

    async def _run_test() -> Any:
        nonlocal calls

        async def _always_failing_coro() -> None:
            nonlocal calls
            calls += 1
            raise OperationalError("stmt", {}, _FakeDriverError("40001"))

        return await mtproto_store._retry_write(_always_failing_coro)

    assert asyncio.run(_run_test()) is None
    assert calls == 3


def test_retry_write_does_not_retry_non_transient_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A non-transient failure is logged and degrades to None (no retry)."""
    monkeypatch.setattr(mtproto_store, "db_call", identity_db_call)
    calls = 0

    async def _run_test() -> Any:
        nonlocal calls

        async def _non_transient_coro() -> None:
            nonlocal calls
            calls += 1
            raise OperationalError("stmt", {}, _FakeDriverError("42P01"))

        return await mtproto_store._retry_write(_non_transient_coro)

    assert asyncio.run(_run_test()) is None
    assert calls == 1


def test_retry_write_connectivity_degrades_immediately(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unreachable server degrades once: the timeout already elapsed."""
    monkeypatch.setattr(mtproto_store, "db_call", identity_db_call)
    calls = 0

    async def _run_test() -> Any:
        nonlocal calls

        async def _failing_coro() -> None:
            nonlocal calls
            calls += 1
            raise OperationalError("stmt", {}, _FakeDriverError("08006"))

        return await mtproto_store._retry_write(_failing_coro)

    assert asyncio.run(_run_test()) is None
    assert calls == 1


def test_retry_write_connection_failure_degrades_immediately(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A dropped connection shares the same single-attempt degrade."""
    monkeypatch.setattr(mtproto_store, "db_call", identity_db_call)
    monkeypatch.setattr(mtproto_store, "_RETRY_BASE_DELAY", 0.0)
    calls = 0

    async def _run_test() -> Any:
        nonlocal calls

        async def _failing_coro() -> None:
            nonlocal calls
            calls += 1
            raise InterfaceError("stmt", {}, _FakeDriverError("connection closed"))

        return await mtproto_store._retry_write(_failing_coro)

    assert asyncio.run(_run_test()) is None
    assert calls == 3


def test_retry_write_circuit_open_degrades_immediately(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An open circuit degrades once with no retry."""
    monkeypatch.setattr(mtproto_store, "db_call", identity_db_call)
    calls = 0

    async def _run_test() -> Any:
        nonlocal calls

        async def _failing_coro() -> None:
            nonlocal calls
            calls += 1
            raise CircuitOpenError("Circuit [postgres] is OPEN; call rejected.")

        return await mtproto_store._retry_write(_failing_coro)

    assert asyncio.run(_run_test()) is None
    assert calls == 1


def test_retry_write_integrity_error_propagates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An integrity error is fencing control flow and must never be swallowed."""
    monkeypatch.setattr(mtproto_store, "db_call", identity_db_call)
    calls = 0

    async def _run_test() -> None:
        nonlocal calls

        async def _dup_coro() -> None:
            nonlocal calls
            calls += 1
            raise IntegrityError("stmt", {}, _FakeDriverError("23505"))

        with pytest.raises(IntegrityError):
            await mtproto_store._retry_write(_dup_coro)

    asyncio.run(_run_test())
    assert calls == 1


# ─────────────────────── Round trips on a server ─────────────────── #


@pytest.fixture
async def postgres_store(postgres_db: str) -> AsyncIterator[PostgresStorage]:
    """Return a store backed by the test database with an empty state table."""
    await engine_module.run(mtproto_state.delete())
    yield PostgresStorage("test")
    await engine_module.run(mtproto_state.delete())


async def test_the_scalar_round_trips(postgres_store: PostgresStorage) -> None:
    """A stored session value comes back unchanged."""
    await postgres_store.auth_key(b"\x01\x02")
    await postgres_store.user_id(7)

    assert await postgres_store.auth_key() == b"\x01\x02"
    assert await postgres_store.user_id() == 7
    assert await postgres_store.dc_id() is None


async def test_the_peers_round_trip(postgres_store: PostgresStorage) -> None:
    """A peer written with a name list is found by both lookups."""
    await postgres_store.update_peers([(42, 99, "user", None)])
    await postgres_store.update_usernames([(42, ["ghost", None])])

    peer = await postgres_store.get_peer_by_id(42)

    assert (peer.user_id, peer.access_hash) == (42, 99)
    assert (await postgres_store.get_peer_by_username("ghost")).user_id == 42


async def test_the_missing_peer_raises_keyerror(
    postgres_store: PostgresStorage,
) -> None:
    """An unknown peer is a miss against the real table too."""
    with pytest.raises(KeyError):
        await postgres_store.get_peer_by_id(1)
    with pytest.raises(KeyError):
        await postgres_store.get_peer_by_username("nobody")


async def test_the_expired_username_raises_keyerror(
    postgres_store: PostgresStorage,
) -> None:
    """A name list older than the TTL is a miss."""
    await postgres_store.update_peers([(42, 99, "user", None)])
    await postgres_store.update_usernames([(42, ["ghost"])])
    await engine_module.run(
        mtproto_state.update()
        .where(mtproto_state.c.id == "test:peer:42")
        .values(updated_on=int(time.time()) - 10 * 60 * 60)
    )

    with pytest.raises(KeyError):
        await postgres_store.get_peer_by_username("ghost")


async def test_the_update_states_merge_and_delete(
    postgres_store: PostgresStorage,
) -> None:
    """A later state fills the fields the earlier one left empty."""
    await postgres_store.set_update_state(UpdateState(0, 10, None, 5, 1))
    await postgres_store.set_update_state(UpdateState(0, None, 20, None, None))

    (merged,) = await postgres_store.get_update_states(0)
    assert (merged.pts, merged.qts, merged.date, merged.seq) == (10, 20, 5, 1)

    await postgres_store.delete_update_state(0)
    assert await postgres_store.get_update_states() == []


async def test_the_namespaces_do_not_leak(postgres_store: PostgresStorage) -> None:
    """A session never reads or removes the rows of another session."""
    other = PostgresStorage("other")
    await postgres_store.user_id(7)
    await other.user_id(8)

    assert await postgres_store.user_id() == 7
    assert await other.user_id() == 8

    await postgres_store.delete()
    assert await postgres_store.user_id() is None
    assert await other.user_id() == 8
