# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Startup warms the caches that the first user-visible update reads."""

from __future__ import annotations

from typing import Any

import pytest

from tcbot import __main__ as app
from tcbot import database as db


@pytest.mark.asyncio
async def test_the_first_command_does_not_pay_a_cold_locale_miss(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    read: list[str] = []

    async def _owner() -> int:
        read.append("owner")
        return 7

    async def _groups() -> list[Any]:
        read.append("groups")
        return []

    async def _community() -> str:
        read.append("community_locale")
        return "en-US"

    async def _role(user_id: int) -> str:
        read.append(f"role:{user_id}")
        return "owner"

    async def _locale(user_id: int) -> str:
        read.append(f"user_locale:{user_id}")
        return "en-US"

    monkeypatch.setattr(db.users_roles, "get_owner_id", _owner)
    monkeypatch.setattr(db.groups_db, "active_groups", _groups)
    monkeypatch.setattr(db.settings_db, "get_community_locale", _community)
    monkeypatch.setattr(db.users_roles, "get_effective_role", _role)
    monkeypatch.setattr(db.settings_db, "get_user_locale", _locale)

    await app._warm_hot_caches()

    assert read == [
        "owner",
        "groups",
        "community_locale",
        "role:7",
        "user_locale:7",
    ]
