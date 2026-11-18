# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Group locale reads share a two-level cache and stay coherent on writes."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from tcbot.database import groups_db as _locale_mod
from tcbot.database.cache import group_locale_cache
from tcbot.database.cache.singletons import _ALL_GROUPS_KEY
from tests.postgres_support import reset_community, seed_users

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


@pytest.fixture
async def group_db(postgres_db: str) -> AsyncIterator[str]:
    """Start from an empty group registry."""
    await reset_community()
    await seed_users(1)
    yield postgres_db
    await reset_community()
    group_locale_cache.clear()


class _RecordingCache:
    """Cache double recording every invalidated key."""

    def __init__(self) -> None:
        self.invalidated: list[str] = []

    def invalidate(self, key: str) -> None:
        self.invalidated.append(key)


async def test_set_group_locale_invalidates_active_groups_cache(
    group_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A locale change must drop the stale groups list and the locale entry."""
    await _locale_mod.add_group(123, "Group", 1)
    await _locale_mod.get_group_locale(123)
    group_locale_cache.put(123, "id-ID")
    cache = _RecordingCache()
    monkeypatch.setattr(_locale_mod, "active_groups_cache", cache)

    matched = await _locale_mod.set_group_locale(123, "en-US")

    assert matched is True
    assert cache.invalidated == [_ALL_GROUPS_KEY]
    # * The next read must reach the row instead of the pre-write entry.
    assert await _locale_mod.get_group_locale(123) == "en-US"


async def test_set_group_locale_none_also_invalidates(
    group_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Clearing the locale invalidates the same caches."""
    await _locale_mod.add_group(456, "Group", 1)
    group_locale_cache.put(456, "id-ID")
    cache = _RecordingCache()
    monkeypatch.setattr(_locale_mod, "active_groups_cache", cache)

    matched = await _locale_mod.set_group_locale(456, None)

    assert matched is True
    assert cache.invalidated == [_ALL_GROUPS_KEY]
    assert await _locale_mod.get_group_locale(456) is None


async def test_setting_the_locale_of_an_unknown_group_reports_no_match(
    group_db: str,
) -> None:
    """A group that is not connected has no locale to store."""
    assert await _locale_mod.set_group_locale(999, "en-US") is False
