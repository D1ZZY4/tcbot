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
    calls = {"owner": 0, "admin": 0, "role": 0}

    async def _owner(user_id: int) -> bool:
        calls["owner"] += 1
        assert user_id == uid
        return False

    async def _admin(user_id: int) -> bool:
        calls["admin"] += 1
        assert user_id == uid
        return True

    async def _role(user_id: int) -> str | None:
        calls["role"] += 1
        assert user_id == uid
        return None

    monkeypatch.setattr(users_roles, "is_owner", _owner)
    monkeypatch.setattr(users_roles, "is_admin", _admin)
    monkeypatch.setattr(users_roles, "get_role", _role)
    try:
        first = asyncio.run(users_roles.get_effective_role(uid))
        second = asyncio.run(users_roles.get_effective_role(uid))
    finally:
        _invalidate(uid)

    assert first == "admin"
    assert second == "admin"
    assert calls == {"owner": 1, "admin": 1, "role": 1}


def test_is_staff_reuses_effective_role_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    uid = 61002
    _invalidate(uid)
    calls = {"owner": 0, "admin": 0, "role": 0}

    async def _owner(user_id: int) -> bool:
        calls["owner"] += 1
        assert user_id == uid
        return False

    async def _admin(user_id: int) -> bool:
        calls["admin"] += 1
        assert user_id == uid
        return True

    async def _role(user_id: int) -> str | None:
        calls["role"] += 1
        assert user_id == uid
        return None

    monkeypatch.setattr(users_roles, "is_owner", _owner)
    monkeypatch.setattr(users_roles, "is_admin", _admin)
    monkeypatch.setattr(users_roles, "get_role", _role)
    try:
        primed = asyncio.run(users_roles.get_effective_role(uid))
        staff_first = asyncio.run(users_roles.is_staff(uid))
        staff_second = asyncio.run(users_roles.is_staff(uid))
    finally:
        _invalidate(uid)

    assert primed == "admin"
    assert staff_first is True
    assert staff_second is True
    assert calls == {"owner": 1, "admin": 1, "role": 1}


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

    async def _owner(user_id: int) -> bool:
        assert user_id == uid
        return False

    async def _boom_admin(user_id: int) -> bool:
        assert user_id == uid
        raise RuntimeError("admin collection down")

    async def _role(user_id: int) -> str | None:
        assert user_id == uid
        return None

    monkeypatch.setattr(users_roles, "is_owner", _owner)
    monkeypatch.setattr(users_roles, "is_admin", _boom_admin)
    monkeypatch.setattr(users_roles, "get_role", _role)
    try:
        with pytest.raises(RuntimeError, match="admin collection down"):
            asyncio.run(users_roles.get_effective_role(uid))

        async def _recovered_admin(user_id: int) -> bool:
            assert user_id == uid
            return False

        async def _recovered_role(user_id: int) -> str | None:
            assert user_id == uid
            return "tester"

        monkeypatch.setattr(users_roles, "is_admin", _recovered_admin)
        monkeypatch.setattr(users_roles, "get_role", _recovered_role)
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


def test_founder_only_diverges_from_admin_membership(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    uid = 61006
    _invalidate(uid)

    async def _owner(user_id: int) -> bool:
        assert user_id == uid
        return True

    async def _not_admin(user_id: int) -> bool:
        assert user_id == uid
        return False

    async def _no_role(user_id: int) -> str | None:
        assert user_id == uid
        return None

    monkeypatch.setattr(users_roles, "is_owner", _owner)
    monkeypatch.setattr(users_roles, "is_admin", _not_admin)
    monkeypatch.setattr(users_roles, "get_role", _no_role)
    try:
        effective = asyncio.run(users_roles.get_effective_role(uid))
    finally:
        _invalidate(uid)

    # * Founder without an admin row resolves to founder, so a naive
    # * cached is_admin built as role in (founder, admin) would flip False to True.
    assert effective == "founder"
    assert asyncio.run(_not_admin(uid)) is False
    assert effective in ("founder", "admin")


def test_founder_plus_admin_shadows_admin_role(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    uid = 61007
    _invalidate(uid)

    async def _owner(user_id: int) -> bool:
        assert user_id == uid
        return True

    async def _admin(user_id: int) -> bool:
        assert user_id == uid
        return True

    async def _no_role(user_id: int) -> str | None:
        assert user_id == uid
        return None

    monkeypatch.setattr(users_roles, "is_owner", _owner)
    monkeypatch.setattr(users_roles, "is_admin", _admin)
    monkeypatch.setattr(users_roles, "get_role", _no_role)
    try:
        effective = asyncio.run(users_roles.get_effective_role(uid))
    finally:
        _invalidate(uid)

    # * Owner plus admin resolves to founder, so a naive cached is_admin
    # * built as role == admin would flip True to False.
    assert effective == "founder"
    assert asyncio.run(_admin(uid)) is True
    assert (effective == "admin") is False


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
