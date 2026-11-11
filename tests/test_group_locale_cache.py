# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Group locale writes keep the locale L1 and the groups-list cache coherent."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from tcbot.database import engine as engine_module
from tcbot.database import groups_db as _locale_mod
from tcbot.database.base import federated_groups
from tcbot.database.cache import _ALL_GROUPS_KEY

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


@pytest.fixture
async def group_db(postgres_db: str) -> AsyncIterator[str]:
    """Start from an empty group table."""
    await engine_module.run(federated_groups.delete())
    yield postgres_db
    await engine_module.run(federated_groups.delete())
    _locale_mod._GROUP_LOCALE_L1.clear()


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
    cache = _RecordingCache()
    monkeypatch.setattr(_locale_mod, "active_groups_cache", cache)
    _locale_mod._GROUP_LOCALE_L1[123] = "id-ID"

    matched = await _locale_mod.set_group_locale(123, "en-US")

    assert matched is True
    assert cache.invalidated == [_ALL_GROUPS_KEY]
    assert 123 not in _locale_mod._GROUP_LOCALE_L1
    assert await _locale_mod.get_group_locale(123) == "en-US"


async def test_set_group_locale_none_also_invalidates(
    group_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Clearing the locale invalidates the same caches."""
    await _locale_mod.add_group(456, "Group", 1)
    cache = _RecordingCache()
    monkeypatch.setattr(_locale_mod, "active_groups_cache", cache)

    matched = await _locale_mod.set_group_locale(456, None)

    assert matched is True
    assert cache.invalidated == [_ALL_GROUPS_KEY]


async def test_setting_the_locale_of_an_unknown_group_reports_no_match(
    group_db: str,
) -> None:
    """A group that is not connected has no locale to store."""
    assert await _locale_mod.set_group_locale(999, "en-US") is False
