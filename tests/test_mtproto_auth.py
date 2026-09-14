# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""MTProto one-time authorization: code/password flows against fakes, no network."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from tcbot.database import mongos as mongos_mod
from tcbot.database import mtproto, mtproto_auth


@pytest.fixture
def _mongo_connected(monkeypatch: pytest.MonkeyPatch) -> list[bool]:
    """Stub the database connection authorize() now requires for shared storage."""
    connected: list[bool] = []

    async def _connect() -> None:
        connected.append(True)

    monkeypatch.setattr(mongos_mod, "connect", _connect)
    return connected


class _Sent:
    phone_code_hash = "hash"


class _FakeClient:
    """Kurigram client double recording the auth call sequence."""

    def __init__(self, *, me: Any = None, password_needed: bool = False) -> None:
        self._me = me
        self._password_needed = password_needed
        self.calls: list[str] = []
        self.is_connected = True

    async def connect(self) -> None:
        self.calls.append("connect")

    async def disconnect(self) -> None:
        self.calls.append("disconnect")

    async def get_me(self) -> Any:
        if self._me is None:
            raise RuntimeError("unauthorized")
        return self._me

    async def send_code(self, _phone: str) -> Any:
        self.calls.append("send_code")
        return _Sent()

    async def sign_in(self, _phone: str, _hash: str, _code: str) -> Any:
        self.calls.append("sign_in")
        if _code != "12345":
            raise mtproto_auth.PhoneCodeInvalid()
        if self._password_needed:
            raise mtproto_auth.SessionPasswordNeeded()
        self._me = _FakeMe()
        return self._me

    async def check_password(self, password: str) -> Any:
        self.calls.append("check_password")
        if password != "secret":
            raise mtproto_auth.PasswordHashInvalid()
        self._me = _FakeMe()
        return self._me


class _FakeMe:
    id = 7


def _run(phone: str = "+62000", code: str = "12345", password: str = "secret") -> str:
    return asyncio.run(
        mtproto_auth.authorize(
            phone, code_fn=lambda _p: code, password_fn=lambda _p: password
        )
    )


def test_happy_path_returns_session_path(
    monkeypatch: pytest.MonkeyPatch, _mongo_connected: list[bool]
) -> None:
    fake = _FakeClient()
    monkeypatch.setattr(mtproto, "_client", fake)

    path = _run()

    assert path == f"mongodb:mtproto_state:{mtproto.cfg.mtproto_session}"
    assert fake.calls == ["connect", "send_code", "sign_in", "disconnect"]


def test_already_authorized_skips_code(
    monkeypatch: pytest.MonkeyPatch, _mongo_connected: list[bool]
) -> None:
    fake = _FakeClient(me=_FakeMe())
    monkeypatch.setattr(mtproto, "_client", fake)

    _run()

    assert fake.calls == ["connect", "disconnect"]


def test_two_factor_flow(
    monkeypatch: pytest.MonkeyPatch, _mongo_connected: list[bool]
) -> None:
    fake = _FakeClient(password_needed=True)
    monkeypatch.setattr(mtproto, "_client", fake)

    _run()

    assert fake.calls == [
        "connect",
        "send_code",
        "sign_in",
        "check_password",
        "disconnect",
    ]


def test_wrong_code_fails(
    monkeypatch: pytest.MonkeyPatch, _mongo_connected: list[bool]
) -> None:
    monkeypatch.setattr(mtproto, "_client", _FakeClient())

    with pytest.raises(RuntimeError, match="Login code rejected"):
        _run(code="00000")


def test_wrong_password_fails(
    monkeypatch: pytest.MonkeyPatch, _mongo_connected: list[bool]
) -> None:
    monkeypatch.setattr(mtproto, "_client", _FakeClient(password_needed=True))

    with pytest.raises(RuntimeError, match="Wrong 2FA password"):
        _run(password="nope")


def test_authorize_connects_mongo_first(
    monkeypatch: pytest.MonkeyPatch, _mongo_connected: list[bool]
) -> None:
    """Regression: shared DB storage needs connect() before any storage op."""
    monkeypatch.setattr(mtproto, "_client", _FakeClient(me=_FakeMe()))

    _run()

    assert _mongo_connected == [True]


def test_unconfigured_fails_without_network(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mtproto, "is_configured", lambda: False)

    with pytest.raises(RuntimeError, match="not set"):
        _run()
