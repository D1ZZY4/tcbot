# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Stats role counts: role_count helper and Stats.main count-only role reads."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from tcbot import database as db
from tcbot.database import users_roles
from tcbot.modules.helper.workflows.stats_flow import Stats


class _SpyCollection:
    """Collection double recording every count_documents filter."""

    def __init__(self) -> None:
        self.filters: list[dict[str, str]] = []

    async def count_documents(self, filter: dict[str, str]) -> int:
        self.filters.append(filter)
        return 42


async def _identity(coro: Any) -> Any:
    return await coro


def test_role_count_delegates_to_count_documents(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _SpyCollection()
    monkeypatch.setattr(users_roles, "col", lambda _name: fake)
    monkeypatch.setattr(users_roles, "db_call", _identity)

    result = asyncio.run(users_roles.role_count("developer"))

    assert result == 42
    assert fake.filters == [{"role": "developer"}]


def _stub_stats_reads(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Stub every Stats.main DB read; record any all_by_role calls."""
    called_all_by_role: list[str] = []

    async def _owner_id() -> int | None:
        return 0

    async def _admin_count() -> int:
        return 5

    async def _role_count(role: str) -> int:
        return {"developer": 2, "tester": 3}[role]

    async def _fail_all_by_role(role: str) -> list[object]:
        called_all_by_role.append(role)
        return []

    async def _ban_count() -> int:
        return 4

    async def _group_count() -> int:
        return 2

    async def _user_count() -> int:
        return 100

    async def _not_owner(_user_id: int) -> bool:
        return False

    async def _no_role(_user_id: int) -> str | None:
        return None

    monkeypatch.setattr(db.users_roles, "get_owner_id", _owner_id)
    monkeypatch.setattr(db.users_roles, "admin_count", _admin_count)
    monkeypatch.setattr(db.users_roles, "role_count", _role_count)
    monkeypatch.setattr(db.users_roles, "all_by_role", _fail_all_by_role)
    monkeypatch.setattr(db.users_roles, "is_owner", _not_owner)
    monkeypatch.setattr(db.users_roles, "get_effective_role", _no_role)
    monkeypatch.setattr(db.bans_db, "active_ban_count", _ban_count)
    monkeypatch.setattr(db.groups_db, "active_group_count", _group_count)
    monkeypatch.setattr(db.users_cache, "total_users", _user_count)
    return called_all_by_role


def test_stats_main_uses_role_counts_not_docs(monkeypatch: pytest.MonkeyPatch) -> None:
    called_all_by_role = _stub_stats_reads(monkeypatch)

    text, _kb = asyncio.run(Stats.main(viewer_id=1))

    assert called_all_by_role == []
    assert "Staff: *10*" in text
    assert "Devs 2, Testers 3" in text
