# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""MTProto mandatory client: missing credentials or login fail fast, never degrade."""

from __future__ import annotations

import asyncio
import dataclasses
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from tcbot.database import mtproto
from tcbot.modules.helper import extraction


def _with_creds(monkeypatch: pytest.MonkeyPatch, api_id: int, api_hash: str) -> None:
    monkeypatch.setattr(mtproto, "_client", None)
    monkeypatch.setattr(
        mtproto.cfg,
        "_c",
        dataclasses.replace(mtproto.cfg._c, api_id=api_id, api_hash=api_hash),
    )


def test_client_raises_without_creds(monkeypatch: pytest.MonkeyPatch) -> None:
    _with_creds(monkeypatch, 0, "")

    assert mtproto.is_configured() is False
    with pytest.raises(RuntimeError, match="API_ID/API_HASH"):
        mtproto.client()


def test_configured_builds_singleton_without_connecting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _with_creds(monkeypatch, 12345, "hash")

    first = mtproto.client()

    assert first is not None
    assert mtproto.client() is first


class _FakeMTUser:
    def __init__(
        self,
        fname: str = "Ghost",
        uname: str | None = "ghost",
        lname: str | None = None,
    ) -> None:
        self.first_name = fname
        self.username = uname
        self.last_name = lname


class _FloodWait(Exception):
    def __init__(self) -> None:
        super().__init__("flood")
        self.value = 5


class _FakeStorage:
    def __init__(self, user_id: int | None = 7) -> None:
        self._user_id = user_id

    async def open(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def user_id(self) -> int | None:
        return self._user_id


class _FakeClient:
    """Kurigram client double: never touches the network."""

    def __init__(
        self, *, connected: bool = True, error: Any = None, user_id: int | None = 7
    ) -> None:
        self.is_connected = connected
        self.storage = _FakeStorage(user_id)
        self._error = error
        self.start_called = False
        self.stopped = False

    async def start(self) -> None:
        self.start_called = True
        if self._error is not None:
            raise self._error
        self.is_connected = True

    async def stop(self) -> None:
        self.stopped = True

    async def get_users(self, _user_id: int) -> Any:
        if self._error is not None:
            raise self._error
        return _FakeMTUser()


def test_start_raises_when_unconfigured(monkeypatch: pytest.MonkeyPatch) -> None:
    _with_creds(monkeypatch, 0, "")

    with pytest.raises(RuntimeError, match="API_ID/API_HASH"):
        asyncio.run(mtproto.start())


def test_start_raises_on_fresh_session_without_prompting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A never-authorized session must fail fast, never reach the stdin prompt."""
    _with_creds(monkeypatch, 12345, "hash")
    fake = _FakeClient(connected=False, user_id=None)
    monkeypatch.setattr(mtproto, "_client", fake)

    with pytest.raises(RuntimeError, match="not authorized"):
        asyncio.run(mtproto.start())
    assert fake.start_called is False


def test_start_true_when_session_authorized(monkeypatch: pytest.MonkeyPatch) -> None:
    _with_creds(monkeypatch, 12345, "hash")
    fake = _FakeClient(connected=False, user_id=7)
    monkeypatch.setattr(mtproto, "_client", fake)

    assert asyncio.run(mtproto.start()) is True
    assert fake.start_called is True


def test_start_raises_on_connect_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    _with_creds(monkeypatch, 12345, "hash")
    monkeypatch.setattr(
        mtproto,
        "_client",
        _FakeClient(connected=False, error=RuntimeError("unauthorized")),
    )

    with pytest.raises(RuntimeError, match="MTProto start failed"):
        asyncio.run(mtproto.start())


def test_stop_clears_client(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeClient()
    monkeypatch.setattr(mtproto, "_client", fake)

    asyncio.run(mtproto.stop())

    assert fake.stopped is True
    assert mtproto._client is None


def test_resolve_none_when_unconfigured(monkeypatch: pytest.MonkeyPatch) -> None:
    _with_creds(monkeypatch, 0, "")

    assert asyncio.run(mtproto.resolve_user(42)) is None


def test_resolve_maps_triple(monkeypatch: pytest.MonkeyPatch) -> None:
    _with_creds(monkeypatch, 12345, "hash")
    monkeypatch.setattr(mtproto, "_client", _FakeClient())

    assert asyncio.run(mtproto.resolve_user(42)) == ("Ghost", "ghost", None)


def test_resolve_none_on_unknown_peer(monkeypatch: pytest.MonkeyPatch) -> None:
    _with_creds(monkeypatch, 12345, "hash")
    monkeypatch.setattr(
        mtproto, "_client", _FakeClient(error=RuntimeError("peer invalid"))
    )

    assert asyncio.run(mtproto.resolve_user(42)) is None


def test_resolve_none_on_flood_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    _with_creds(monkeypatch, 12345, "hash")
    monkeypatch.setattr(mtproto, "_client", _FakeClient(error=_FloodWait()))

    assert asyncio.run(mtproto.resolve_user(42)) is None


def test_resolve_none_when_disconnected(monkeypatch: pytest.MonkeyPatch) -> None:
    _with_creds(monkeypatch, 12345, "hash")
    monkeypatch.setattr(mtproto, "_client", _FakeClient(connected=False))

    assert asyncio.run(mtproto.resolve_user(42)) is None


def test_resolve_propagates_cancel(monkeypatch: pytest.MonkeyPatch) -> None:
    _with_creds(monkeypatch, 12345, "hash")
    monkeypatch.setattr(mtproto, "_client", _FakeClient(error=asyncio.CancelledError()))

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(mtproto.resolve_user(42))


class _BlindBot:
    """Bot double whose Bot API lookups always fail."""

    async def get_chat(self, _ident: object) -> object:
        raise RuntimeError("unknown peer")


def test_fetch_live_identity_prefers_mtproto_over_sweep(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _hit(user_id: int) -> tuple[str, str | None, str | None]:
        return ("Ghost", "ghost", None)

    async def _must_not_run() -> object:
        raise AssertionError("group sweep must be skipped on MTProto hit")

    monkeypatch.setattr(extraction.db.mtproto, "resolve_user", _hit)
    monkeypatch.setattr(extraction.db.groups_db, "active_groups", _must_not_run)

    assert asyncio.run(
        extraction._fetch_live_identity(_BlindBot(), 42)  # type: ignore[arg-type]
    ) == (
        "Ghost",
        "ghost",
        None,
    )


class _RecordingStore:
    """Storage double recording what the legacy import wrote."""

    def __init__(self) -> None:
        self.scalars: dict[str, object] = {}
        self.peers: list[tuple[int, int, str, str | None]] = []
        self.names: list[tuple[int, list[str | None]]] = []
        self.states: list[object] = []

    async def _accessor(self, name: str, value: object = object) -> object:
        if value is object:
            return self.scalars.get(name)
        self.scalars[name] = value
        return None

    async def __getattr__(self, name: str) -> object:
        async def _scalar(value: object = object) -> object:
            return await self._accessor(name, value)

        return _scalar

    async def update_peers(self, peers: list[tuple[int, int, str, str | None]]) -> None:
        self.peers.extend(peers)

    async def update_usernames(
        self, usernames: list[tuple[int, list[str | None]]]
    ) -> None:
        self.names.extend(usernames)

    async def set_update_state(self, state: object) -> None:
        self.states.append(state)


def _legacy_db(path: object, *, user_id: int | None = 7) -> None:
    db = sqlite3.connect(str(path))
    db.execute(
        "CREATE TABLE sessions (dc_id, server_address, port, api_id, test_mode,"
        " auth_key, date, user_id, is_bot)"
    )
    db.execute(
        "INSERT INTO sessions VALUES (2, 'x', 443, 1, 0, X'00', 0, ?, 0)", (user_id,)
    )
    db.execute(
        "CREATE TABLE peers (id, access_hash, type, phone_number, last_update_on)"
    )
    db.execute("INSERT INTO peers VALUES (42, 99, 'user', NULL, 0)")
    db.execute("CREATE TABLE usernames (id, username)")
    db.execute("INSERT INTO usernames VALUES (42, 'ghost')")
    db.execute("CREATE TABLE update_state (id, pts, qts, date, seq)")
    db.execute("INSERT INTO update_state VALUES (0, 10, 20, 5, 1)")
    db.commit()
    db.close()


def test_import_legacy_file_authorizes_store(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    session = Path(str(tmp_path)) / f"{mtproto.cfg.mtproto_session}.session"
    _legacy_db(session)
    monkeypatch.chdir(tmp_path)

    store = _RecordingStore()

    assert asyncio.run(mtproto._import_legacy_file(store)) is True  # type: ignore[arg-type]
    assert store.scalars.get("user_id") == 7
    assert store.peers == [(42, 99, "user", None)]
    assert store.names == [(42, ["ghost"])]
    assert len(store.states) == 1


def test_import_legacy_file_skips_unauthorized(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    session = Path(str(tmp_path)) / f"{mtproto.cfg.mtproto_session}.session"
    _legacy_db(session, user_id=None)
    monkeypatch.chdir(tmp_path)

    assert asyncio.run(mtproto._import_legacy_file(_RecordingStore())) is False  # type: ignore[arg-type]


def test_import_legacy_file_skips_junk(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # * Wrong session name: the configured legacy path is absent.
    Path(str(tmp_path)).joinpath("other-name.session").write_text("junk")
    monkeypatch.chdir(tmp_path)

    assert asyncio.run(mtproto._import_legacy_file(_RecordingStore())) is False  # type: ignore[arg-type]


class _FakeMember:
    def __init__(
        self,
        uid: int,
        fname: str | None,
        uname: str | None = None,
        *,
        bot: bool = False,
    ) -> None:
        self.user = SimpleNamespace(
            id=uid, first_name=fname, username=uname, last_name=None, is_bot=bot
        )


class _HarvestClient(_FakeClient):
    def __init__(
        self, members: list[_FakeMember], error: BaseException | None = None
    ) -> None:
        super().__init__()
        self._members = members
        self._harvest_error = error

    async def get_chat_members(self, _chat_id: int, limit: int = 0):  # type: ignore[no-untyped-def]
        for member in self._members[: limit or len(self._members)]:
            yield member
        if self._harvest_error is not None:
            raise self._harvest_error


def test_harvest_group_members_caches_humans(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harvested: list[tuple[int, str | None, str, str | None]] = []

    async def _harvest(
        uid: int, uname: str | None, fname: str, lname: str | None = None
    ) -> bool:
        harvested.append((uid, uname, fname, lname))
        return True

    members = [
        _FakeMember(1, "A", "a"),
        _FakeMember(2, None),
        _FakeMember(3, "C"),
        _FakeMember(4, "B", bot=True),
    ]
    monkeypatch.setattr(mtproto, "_client", _HarvestClient(members))
    monkeypatch.setattr("tcbot.database.users_cache.harvest_user_identity", _harvest)

    assert asyncio.run(mtproto.harvest_group_members(-1001, limit=10)) == 2
    assert harvested == [(1, "a", "A", None), (3, None, "C", None)]


def test_harvest_group_members_stops_early_on_flood(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harvested: list[int] = []

    async def _harvest(
        uid: int, uname: str | None, fname: str, lname: str | None = None
    ) -> bool:
        harvested.append(uid)
        return True

    monkeypatch.setattr(
        mtproto, "_client", _HarvestClient([_FakeMember(1, "A")], error=_FloodWait())
    )
    monkeypatch.setattr("tcbot.database.users_cache.harvest_user_identity", _harvest)

    assert asyncio.run(mtproto.harvest_group_members(-1001)) == 1
    assert harvested == [1]
