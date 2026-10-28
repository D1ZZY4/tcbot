# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""set_owner cleanup delete: bounded retry, operator guidance, cancellation."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import pytest

from tcbot.database import users_roles
from tcbot.database.cache import _OWNER_KEY


async def _identity(coro: Any) -> Any:
    return await coro


class _FakeOwnerCol:
    """In-memory tc_owners fake whose delete_many fails a bounded number of times."""

    def __init__(
        self,
        *,
        delete_failures: int = 0,
        permanent_failure: bool = False,
    ) -> None:
        self.replace_calls = 0
        self.delete_calls = 0
        self.count_calls = 0
        self._delete_failures = delete_failures
        self._permanent_failure = permanent_failure

    async def find_one_and_replace(self, *args: Any, **kwargs: Any) -> None:
        self.replace_calls += 1

    async def delete_many(self, *args: Any, **kwargs: Any) -> None:
        self.delete_calls += 1
        if self._permanent_failure or self.delete_calls <= self._delete_failures:
            raise RuntimeError("tc_owners delete failed")

    async def estimated_document_count(self) -> int:
        self.count_calls += 1
        return 1


def _install_sleep_spy(monkeypatch: pytest.MonkeyPatch, sleeps: list[float]) -> None:
    """Route the module's asyncio.sleep calls into *sleeps* instead of waiting."""

    async def _spy(delay: float, *args: Any, **kwargs: Any) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(users_roles.asyncio, "sleep", _spy)


def test_set_owner_retries_transient_delete_then_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    uid = 61009
    col_obj = _FakeOwnerCol(delete_failures=2)
    sleeps: list[float] = []
    monkeypatch.setattr(users_roles, "col", lambda _name: col_obj)
    monkeypatch.setattr(users_roles, "db_call", _identity)
    _install_sleep_spy(monkeypatch, sleeps)
    try:
        asyncio.run(users_roles.set_owner(uid))
        cached = users_roles.owner_id_cache.get(_OWNER_KEY)
    finally:
        users_roles.owner_id_cache.invalidate(_OWNER_KEY)

    assert col_obj.replace_calls == 1
    assert col_obj.delete_calls == 3
    assert col_obj.count_calls == 1
    assert sleeps == [0.5, 1.0]
    assert cached == uid


def test_set_owner_persistent_delete_failure_reraises_with_guidance(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    uid = 61010
    col_obj = _FakeOwnerCol(permanent_failure=True)
    sleeps: list[float] = []
    monkeypatch.setattr(users_roles, "col", lambda _name: col_obj)
    monkeypatch.setattr(users_roles, "db_call", _identity)
    _install_sleep_spy(monkeypatch, sleeps)
    with (
        caplog.at_level(logging.ERROR, logger="tcbot.database.users_roles"),
        pytest.raises(RuntimeError, match="tc_owners delete failed"),
    ):
        asyncio.run(users_roles.set_owner(uid))

    assert col_obj.replace_calls == 1
    assert col_obj.delete_calls == 3
    assert sleeps == [0.5, 1.0]
    assert "tc_owners" in caplog.text
    assert "split brain" in caplog.text
    assert "lowest user_id" in caplog.text


def test_set_owner_delete_cancellation_propagates_without_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    uid = 61011
    delete_calls: list[int] = []

    class _CancelCol:
        async def find_one_and_replace(self, *args: Any, **kwargs: Any) -> None:
            return None

        async def delete_many(self, *args: Any, **kwargs: Any) -> None:
            delete_calls.append(1)
            raise asyncio.CancelledError()

    sleeps: list[float] = []
    monkeypatch.setattr(users_roles, "col", lambda _name: _CancelCol())
    monkeypatch.setattr(users_roles, "db_call", _identity)
    _install_sleep_spy(monkeypatch, sleeps)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(users_roles.set_owner(uid))

    assert delete_calls == [1]
    assert sleeps == []
