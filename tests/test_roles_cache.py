# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Role cache semantics: cached reads versus outage behavior."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from tcbot.database import users_roles
from tcbot.database.cache import _OWNER_KEY
from tests.postgres_support import identity_db_call


async def _identity(op: Any, **_kwargs: Any) -> Any:
    return await identity_db_call(op)


def _invalidate(uid: int) -> None:
    users_roles.effective_role_cache.invalidate(uid)


def test_get_effective_role_caches_second_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    uid = 61001
    _invalidate(uid)
    hits: list[int] = []

    async def _fetch_one(stmt: Any) -> dict[str, str] | None:
        hits.append(uid)
        return {"role_key": "admin"}

    monkeypatch.setattr(users_roles, "fetch_one", _fetch_one)
    monkeypatch.setattr(users_roles, "db_call", _identity)
    try:
        first = asyncio.run(users_roles.get_effective_role(uid))
        second = asyncio.run(users_roles.get_effective_role(uid))
    finally:
        _invalidate(uid)

    assert first == "admin"
    assert second == "admin"
    assert hits == [uid]


def test_is_staff_reuses_effective_role_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    uid = 61002
    _invalidate(uid)
    hits: list[int] = []

    async def _fetch_one(stmt: Any) -> dict[str, str] | None:
        hits.append(uid)
        return {"role_key": "admin"}

    monkeypatch.setattr(users_roles, "fetch_one", _fetch_one)
    monkeypatch.setattr(users_roles, "db_call", _identity)
    try:
        primed = asyncio.run(users_roles.get_effective_role(uid))
        staff_first = asyncio.run(users_roles.is_staff(uid))
        staff_second = asyncio.run(users_roles.is_staff(uid))
    finally:
        _invalidate(uid)

    assert primed == "admin"
    assert staff_first is True
    assert staff_second is True
    assert hits == [uid]


def test_is_admin_hits_db_on_every_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    uid = 61003
    hits: list[int] = []

    async def _fetch_one(stmt: Any) -> dict[str, int] | None:
        hits.append(uid)
        return {"user_id": uid}

    monkeypatch.setattr(users_roles, "fetch_one", _fetch_one)
    monkeypatch.setattr(users_roles, "db_call", _identity)

    first = asyncio.run(users_roles.is_admin(uid))
    second = asyncio.run(users_roles.is_admin(uid))

    assert first is True
    assert second is True
    assert hits == [uid, uid]


def test_get_effective_role_outage_raises_and_does_not_poison(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    uid = 61004
    _invalidate(uid)

    async def _boom(stmt: Any) -> dict[str, str] | None:
        raise RuntimeError("role store down")

    monkeypatch.setattr(users_roles, "fetch_one", _boom)
    monkeypatch.setattr(users_roles, "db_call", _identity)
    try:
        with pytest.raises(RuntimeError, match="role store down"):
            asyncio.run(users_roles.get_effective_role(uid))

        async def _recovered(stmt: Any) -> dict[str, str] | None:
            return {"role_key": "moderator"}

        monkeypatch.setattr(users_roles, "fetch_one", _recovered)
        recovered = asyncio.run(users_roles.get_effective_role(uid))
    finally:
        _invalidate(uid)

    assert recovered == "tester"


def test_is_staff_fail_closed_on_outage_and_reraises_cancelled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    uid = 61005
    _invalidate(uid)

    async def _boom(_user_id: int) -> str | None:
        raise RuntimeError("role store down")

    monkeypatch.setattr(users_roles, "get_effective_role", _boom)
    try:
        assert asyncio.run(users_roles.is_staff(uid)) is False
    finally:
        _invalidate(uid)

    async def _cancelled(_user_id: int, *, fresh: bool = False) -> str | None:
        raise asyncio.CancelledError()

    monkeypatch.setattr(users_roles, "get_effective_role", _cancelled)
    try:
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(users_roles.is_staff(uid))
    finally:
        _invalidate(uid)


def test_the_owner_assignment_resolves_to_the_founder_role(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The community stores the owner, the application calls it founder.

    The storage key and the application vocabulary are different on
    purpose: the application never sees a storage key, so a rename of the
    catalog cannot leak into the handlers.
    """
    uid = 61006
    _invalidate(uid)

    async def _fetch_one(stmt: Any) -> dict[str, str] | None:
        return {"role_key": "owner"}

    monkeypatch.setattr(users_roles, "fetch_one", _fetch_one)
    monkeypatch.setattr(users_roles, "db_call", _identity)
    try:
        effective = asyncio.run(users_roles.get_effective_role(uid))
    finally:
        _invalidate(uid)

    assert effective == "founder"


def test_an_unknown_stored_role_resolves_to_no_role(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A hand-edited row must not grant real privilege."""
    uid = 61007
    _invalidate(uid)

    async def _fetch_one(stmt: Any) -> dict[str, str] | None:
        return {"role_key": "superuser"}

    monkeypatch.setattr(users_roles, "fetch_one", _fetch_one)
    monkeypatch.setattr(users_roles, "db_call", _identity)
    try:
        effective = asyncio.run(users_roles.get_effective_role(uid))
    finally:
        _invalidate(uid)

    assert effective is None


def test_get_owner_id_caches_second_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    users_roles.owner_id_cache.invalidate(_OWNER_KEY)
    hits: list[int] = []

    async def _fetch_one(stmt: Any) -> dict[str, int] | None:
        hits.append(1)
        return {"user_id": 61008}

    monkeypatch.setattr(users_roles, "fetch_one", _fetch_one)
    monkeypatch.setattr(users_roles, "db_call", _identity)
    try:
        first = asyncio.run(users_roles.get_owner_id())
        second = asyncio.run(users_roles.get_owner_id())
    finally:
        users_roles.owner_id_cache.invalidate(_OWNER_KEY)

    assert first == 61008
    assert second == 61008
    assert len(hits) == 1


def test_is_staff_fresh_forwards_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    uid = 61009
    seen: list[bool] = []

    async def _role(user_id: int, *, fresh: bool = False) -> str | None:
        seen.append(fresh)
        return "admin" if fresh else None

    monkeypatch.setattr(users_roles, "get_effective_role", _role)
    # * A stale cached read denies a demoted admin; the fresh read
    # * reflects the live row, so enforcement gates must use it.
    assert asyncio.run(users_roles.is_staff(uid)) is False
    assert asyncio.run(users_roles.is_staff(uid, fresh=True)) is True
    assert seen == [False, True]


def test_is_owner_fresh_bypasses_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    users_roles.owner_id_cache.invalidate(_OWNER_KEY)
    row = {"user_id": 61010}

    async def _fetch_one(stmt: Any) -> dict[str, int] | None:
        return dict(row)

    monkeypatch.setattr(users_roles, "fetch_one", _fetch_one)
    monkeypatch.setattr(users_roles, "db_call", _identity)
    try:
        # * Prime the cache with the first owner row.
        assert asyncio.run(users_roles.is_owner(61010)) is True
        # * A transfer in another process lands; the cached read still
        # * names the old owner while the fresh read sees the new row.
        row["user_id"] = 61011
        assert asyncio.run(users_roles.is_owner(61010)) is True
        assert asyncio.run(users_roles.is_owner(61010, fresh=True)) is False
        assert asyncio.run(users_roles.is_owner(61011, fresh=True)) is True
    finally:
        users_roles.owner_id_cache.invalidate(_OWNER_KEY)


def test_a_demotion_during_a_fresh_read_is_not_undone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A demotion that lands during a fresh read must stay revoked.

    The fresh read resolves the role from the assignments table, so a
    demotion can land between the read and the publish. Publishing the
    stale role would keep the revoked privilege alive for the whole
    cache TTL on every cached read path.
    """
    uid = 61011
    _invalidate(uid)
    started = asyncio.Event()
    release = asyncio.Event()

    async def _fetch_one(stmt: Any) -> dict[str, str] | None:
        started.set()
        await release.wait()
        return {"role_key": "admin"}

    monkeypatch.setattr(users_roles, "fetch_one", _fetch_one)
    monkeypatch.setattr(users_roles, "db_call", _identity)

    async def _scenario() -> None:
        task = asyncio.create_task(users_roles.get_effective_role(uid, fresh=True))
        await started.wait()
        # * The demotion lands while the fresh read is still running.
        users_roles.effective_role_cache.invalidate(uid)
        release.set()
        assert await task == "admin"

    try:
        asyncio.run(_scenario())
        assert users_roles.effective_role_cache.get(uid) != "admin"
    finally:
        _invalidate(uid)
