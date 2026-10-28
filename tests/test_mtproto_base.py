# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""MTProto bot session: automatic login, fail-fast boot, graceful runtime."""

from __future__ import annotations

import asyncio
import dataclasses
from types import SimpleNamespace
from typing import Any

import pytest

from tcbot.database import mtproto
from tcbot.modules.helper import extraction


def _with_creds(monkeypatch: pytest.MonkeyPatch, api_id: int, api_hash: str) -> None:
    monkeypatch.setattr(mtproto, "_client", None)
    # * Lease globals reset: start() success claims ownership and spawns a
    # * heartbeat task, and handle_auth_failure parks permanently. Without
    # * resets one test's claimed/dead state would leak into the next.
    monkeypatch.setattr(mtproto, "_lease_owner", None)
    monkeypatch.setattr(mtproto, "_heartbeat_task", None)
    monkeypatch.setattr(mtproto, "_auth_dead", False)
    monkeypatch.setattr(
        mtproto.cfg,
        "_c",
        dataclasses.replace(mtproto.cfg._c, api_id=api_id, api_hash=api_hash),
    )


async def _claim_ok(self: object, owner: str, *, ttl_s: float) -> bool:
    return True


async def _release_ok(self: object, owner: str) -> None:
    return None


def _stub_lease(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub the owner lease so start()/stop() never touch MongoDB."""
    monkeypatch.setattr(
        "tcbot.database.mtproto_store.MongoStorage.claim_owner", _claim_ok
    )
    monkeypatch.setattr(
        "tcbot.database.mtproto_store.MongoStorage.release_owner", _release_ok
    )


def test_client_raises_without_creds(monkeypatch: pytest.MonkeyPatch) -> None:
    _with_creds(monkeypatch, 0, "")

    assert mtproto.is_configured() is False
    with pytest.raises(RuntimeError, match="API_ID/API_HASH"):
        mtproto.client()


def test_client_builds_singleton_without_connecting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _with_creds(monkeypatch, 12345, "hash")

    first = mtproto.client()

    assert first is not None
    assert mtproto.client() is first


def test_start_raises_when_unconfigured(monkeypatch: pytest.MonkeyPatch) -> None:
    _with_creds(monkeypatch, 0, "")

    with pytest.raises(RuntimeError, match="API_ID/API_HASH"):
        asyncio.run(mtproto.start())


def test_start_connects_bot_session(monkeypatch: pytest.MonkeyPatch) -> None:
    _with_creds(monkeypatch, 12345, "hash")
    _stub_lease(monkeypatch)
    fake = _FakeClient(connected=False)
    monkeypatch.setattr(mtproto, "_client", fake)

    assert asyncio.run(mtproto.start()) is True
    assert fake.start_called is True


def test_start_fatal_when_bot_session_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _with_creds(monkeypatch, 12345, "hash")
    _stub_lease(monkeypatch)
    monkeypatch.setattr(
        mtproto, "_client", _FakeClient(connected=False, error=RuntimeError("down"))
    )

    with pytest.raises(RuntimeError, match="bot session failed"):
        asyncio.run(mtproto.start())


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


class _FakeClient:
    """Kurigram client double: never touches the network."""

    def __init__(self, *, connected: bool = True, error: Any = None) -> None:
        self.is_connected = connected
        self._error = error
        self._user = _FakeMTUser()
        self._resolved: Any = None
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
        return self._user

    async def invoke(self, _query: Any) -> Any:
        if self._error is not None:
            raise self._error
        return self._resolved


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


def _resolved_peer(*users: Any) -> Any:
    return SimpleNamespace(users=list(users))


def test_resolve_username_maps_triple(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeClient()
    fake._resolved = _resolved_peer(
        SimpleNamespace(id=42, first_name="Ghost", username="ghost")
    )
    monkeypatch.setattr(mtproto, "_client", fake)

    assert asyncio.run(mtproto.resolve_username("@ghost")) == (42, "Ghost", "ghost")


def test_resolve_username_none_on_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mtproto, "_client", _FakeClient(error=RuntimeError("taken")))

    assert asyncio.run(mtproto.resolve_username("ghost")) is None


def test_resolve_username_none_when_disconnected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(mtproto, "_client", _FakeClient(connected=False))

    assert asyncio.run(mtproto.resolve_username("ghost")) is None
