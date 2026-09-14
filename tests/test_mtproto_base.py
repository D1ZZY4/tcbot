# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""MTProto base: unconfigured degrades to None, configured builds without connecting."""

from __future__ import annotations

import asyncio
import dataclasses
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


def test_unconfigured_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    _with_creds(monkeypatch, 0, "")

    assert mtproto.is_configured() is False
    assert mtproto.client() is None


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


def test_start_false_when_unconfigured(monkeypatch: pytest.MonkeyPatch) -> None:
    _with_creds(monkeypatch, 0, "")

    assert asyncio.run(mtproto.start()) is False


def test_start_false_on_fresh_session_without_prompting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A never-authorized session must fail fast, never reach the stdin prompt."""
    _with_creds(monkeypatch, 12345, "hash")
    fake = _FakeClient(connected=False, user_id=None)
    monkeypatch.setattr(mtproto, "_client", fake)

    assert asyncio.run(mtproto.start()) is False
    assert fake.start_called is False


def test_start_true_when_session_authorized(monkeypatch: pytest.MonkeyPatch) -> None:
    _with_creds(monkeypatch, 12345, "hash")
    fake = _FakeClient(connected=False, user_id=7)
    monkeypatch.setattr(mtproto, "_client", fake)

    assert asyncio.run(mtproto.start()) is True
    assert fake.start_called is True


def test_start_false_on_auth_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    _with_creds(monkeypatch, 12345, "hash")
    monkeypatch.setattr(
        mtproto,
        "_client",
        _FakeClient(connected=False, error=RuntimeError("unauthorized")),
    )

    assert asyncio.run(mtproto.start()) is False


def test_stop_clears_client(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeClient()
    monkeypatch.setattr(mtproto, "_client", fake)

    asyncio.run(mtproto.stop())

    assert fake.stopped is True
    assert mtproto._client is None


def test_resolve_maps_triple(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mtproto, "_client", _FakeClient())

    assert asyncio.run(mtproto.resolve_user(42)) == ("Ghost", "ghost", None)


def test_resolve_none_on_unknown_peer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        mtproto, "_client", _FakeClient(error=RuntimeError("peer invalid"))
    )

    assert asyncio.run(mtproto.resolve_user(42)) is None


def test_resolve_none_on_flood_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mtproto, "_client", _FakeClient(error=_FloodWait()))

    assert asyncio.run(mtproto.resolve_user(42)) is None


def test_resolve_none_when_disconnected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mtproto, "_client", _FakeClient(connected=False))

    assert asyncio.run(mtproto.resolve_user(42)) is None


def test_resolve_propagates_cancel(monkeypatch: pytest.MonkeyPatch) -> None:
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
