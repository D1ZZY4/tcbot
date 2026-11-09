# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Group locale writes keep the locale L1 and the groups-list cache coherent."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from tcbot.database import groups_db as _locale_mod
from tcbot.database.cache import _ALL_GROUPS_KEY


def test_set_group_locale_invalidates_active_groups_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[str] = []

    class _Cache:
        def invalidate(self, key: str) -> None:
            seen.append(key)

    async def _db_call(coro: Any) -> Any:
        return SimpleNamespace(matched_count=1)

    class _Groups:
        def update_one(self, *args: Any, **kwargs: Any) -> SimpleNamespace:
            return SimpleNamespace()

    monkeypatch.setattr(_locale_mod, "db_call", _db_call)
    monkeypatch.setattr(_locale_mod, "_groups", lambda: _Groups())
    monkeypatch.setattr(_locale_mod, "active_groups_cache", _Cache())
    _locale_mod._GROUP_LOCALE_L1[123] = "id-ID"

    matched = asyncio.run(_locale_mod.set_group_locale(123, "id-ID"))

    assert matched is True
    assert seen == [_ALL_GROUPS_KEY]
    assert 123 not in _locale_mod._GROUP_LOCALE_L1


def test_set_group_locale_none_also_invalidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[str] = []

    class _Cache:
        def invalidate(self, key: str) -> None:
            seen.append(key)

    async def _db_call(coro: Any) -> Any:
        return SimpleNamespace(matched_count=0)

    class _Groups:
        def update_one(self, *args: Any, **kwargs: Any) -> SimpleNamespace:
            return SimpleNamespace()

    monkeypatch.setattr(_locale_mod, "db_call", _db_call)
    monkeypatch.setattr(_locale_mod, "_groups", lambda: _Groups())
    monkeypatch.setattr(_locale_mod, "active_groups_cache", _Cache())

    matched = asyncio.run(_locale_mod.set_group_locale(456, None))

    assert matched is False
    assert seen == [_ALL_GROUPS_KEY]
