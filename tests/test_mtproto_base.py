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
from pyrogram.errors import SessionRevoked

from tcbot import database as db
from tcbot.database import mtproto
from tcbot.modules.helper.extraction.refresh import _fetch_live_identity


def _with_creds(monkeypatch: pytest.MonkeyPatch, api_id: int, api_hash: str) -> None:
    monkeypatch.setattr(mtproto, "_client", None)
    # * Lease globals reset: start() success claims ownership and spawns a
    # * heartbeat task, and handle_auth_failure parks permanently. Without
    # * resets one test's claimed/dead state would leak into the next.
    monkeypatch.setattr(mtproto, "_lease_owner", None)
    monkeypatch.setattr(mtproto, "_heartbeat_task", None)
    monkeypatch.setattr(mtproto, "_auth_dead", False)
    monkeypatch.setattr(
        mtproto,
        "cfg",
        dataclasses.replace(mtproto.cfg, api_id=api_id, api_hash=api_hash),
    )


async def _claim_ok(self: object, owner: str, *, ttl_s: float) -> bool:
    return True


async def _release_ok(self: object, owner: str) -> None:
    return None


async def _refresh_ok(self: object, owner: str, *, ttl_s: float) -> bool:
    return True


async def _clear_ok(self: object) -> None:
    return None


def _stub_lease(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub the owner lease so start()/stop() never touch the database."""
    monkeypatch.setattr(
        "tcbot.database.mtproto_store.PostgresStorage.claim_owner", _claim_ok
    )
    monkeypatch.setattr(
        "tcbot.database.mtproto_store.PostgresStorage.release_owner", _release_ok
    )
    monkeypatch.setattr(
        "tcbot.database.mtproto_store.PostgresStorage.refresh_owner", _refresh_ok
    )
    monkeypatch.setattr(
        "tcbot.database.mtproto_store.PostgresStorage.clear_session_for_relogin",
        _clear_ok,
    )


def test_client_raises_without_creds(monkeypatch: pytest.MonkeyPatch) -> None:
    _with_creds(monkeypatch, 0, "")

    assert mtproto.cfg.mtproto_enabled is False
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


def test_start_recovers_from_a_revoked_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A revoked session is rebuilt once from the bot token under the lease."""
    _with_creds(monkeypatch, 12345, "hash")
    _stub_lease(monkeypatch)
    cleared: list[int] = []

    async def _clear(self: object) -> None:
        cleared.append(1)

    monkeypatch.setattr(
        "tcbot.database.mtproto_store.PostgresStorage.clear_session_for_relogin",
        _clear,
    )
    fake = _FakeClient(connected=False, start_errors=[SessionRevoked()])
    monkeypatch.setattr(mtproto, "_client", fake)

    assert asyncio.run(mtproto.start()) is True
    assert fake.is_connected is True
    assert cleared == [1]
    assert mtproto.is_auth_dead() is False


def test_start_fails_closed_when_session_recovery_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bad credentials must still fail boot after one recovery attempt."""
    _with_creds(monkeypatch, 12345, "hash")
    _stub_lease(monkeypatch)
    fake = _FakeClient(
        connected=False, start_errors=[SessionRevoked(), RuntimeError("bad token")]
    )
    monkeypatch.setattr(mtproto, "_client", fake)

    with pytest.raises(RuntimeError, match="recovery failed"):
        asyncio.run(mtproto.start())
    assert mtproto.is_auth_dead() is True


def test_resolve_parks_the_client_on_a_revoked_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A lookup that reports a revoked session parks MTProto once."""
    _with_creds(monkeypatch, 12345, "hash")
    fake = _FakeClient(error=SessionRevoked())
    monkeypatch.setattr(mtproto, "_client", fake)

    assert asyncio.run(mtproto.resolve_user(42)) is None
    assert mtproto.is_auth_dead() is True
    assert fake.stopped is True
    assert mtproto._client is None


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

    def __init__(
        self,
        *,
        connected: bool = True,
        error: Any = None,
        start_errors: list[BaseException] | None = None,
    ) -> None:
        self.is_connected = connected
        self._error = error
        self._start_errors = start_errors
        self._user: Any = _FakeMTUser()
        self._resolved: Any = None
        self.start_called = False
        self.stopped = False

    async def start(self) -> None:
        self.start_called = True
        if self._start_errors is not None:
            if self._start_errors:
                raise self._start_errors.pop(0)
        elif self._error is not None:
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

    monkeypatch.setattr(db.mtproto, "resolve_user", _hit)
    monkeypatch.setattr(db.groups_db, "active_groups", _must_not_run)

    assert asyncio.run(
        _fetch_live_identity(_BlindBot(), 42)  # type: ignore[arg-type]
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


def test_harvest_resumes_at_the_stored_offset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A slice after the stored cursor skips the members already covered."""
    harvested: list[int] = []
    saved: list[tuple[int, bool]] = []

    async def _harvest(
        uid: int, uname: str | None, fname: str, lname: str | None = None
    ) -> bool:
        harvested.append(uid)
        return True

    async def _load(chat_id: int) -> int:
        return 1

    async def _save(chat_id: int, offset: int, *, complete: bool) -> None:
        saved.append((offset, complete))

    members = [_FakeMember(i, f"M{i}") for i in range(1, 5)]
    monkeypatch.setattr(mtproto, "_client", _HarvestClient(members))
    monkeypatch.setattr("tcbot.database.users_cache.harvest_user_identity", _harvest)
    monkeypatch.setattr(mtproto, "_load_harvest_offset", _load)
    monkeypatch.setattr(mtproto, "_save_harvest_state", _save)

    result = asyncio.run(mtproto.harvest_group_members_result(-1001, limit=2))

    assert harvested == [2, 3]
    assert result.harvested == 2
    assert result.scanned == 2
    assert result.complete is False
    assert result.next_offset == 3
    assert saved == [(3, False)]


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


def test_is_bot_user_maps_the_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeClient()
    fake._user = SimpleNamespace(first_name="Ghost", is_bot=True)
    monkeypatch.setattr(mtproto, "_client", fake)

    assert asyncio.run(mtproto.is_bot_user(42)) is True


def test_is_bot_user_returns_none_for_a_group_peer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A chat peer has no ``is_bot`` flag; it must not read as a human."""
    fake = _FakeClient()
    fake._user = SimpleNamespace(id=-1001, title="Group")
    monkeypatch.setattr(mtproto, "_client", fake)

    assert asyncio.run(mtproto.is_bot_user(-1001)) is None


def test_is_bot_user_returns_none_for_a_nameless_peer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeClient()
    fake._user = SimpleNamespace(first_name="", is_bot=False)
    monkeypatch.setattr(mtproto, "_client", fake)

    assert asyncio.run(mtproto.is_bot_user(42)) is None
