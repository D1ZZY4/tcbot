# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Erasure must survive the identity cache and live verification paths."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError

from tcbot.database import users_cache
from tcbot.database.cache import user_mention_cache
from tcbot.modules.helper.extraction import refresh


@pytest.mark.asyncio
async def test_an_erased_profile_is_not_reverified_from_telegram(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A cleared profile never triggers a live name fetch or a cache write."""
    monkeypatch.setattr(
        users_cache,
        "get_user",
        AsyncMock(
            return_value={
                "first_name": "",
                "username": None,
                "last_name": None,
                "erased_at": datetime(2026, 1, 1, tzinfo=UTC),
                "updated_at": datetime(2020, 1, 1, tzinfo=UTC),
            }
        ),
    )

    async def _no_live_lookup(*_args: Any) -> None:
        raise AssertionError("an erased profile must not be verified live")

    monkeypatch.setattr(refresh, "_fetch_live_identity", _no_live_lookup)
    invalidated: list[int] = []
    monkeypatch.setattr(
        type(user_mention_cache),
        "invalidate",
        lambda _self, key: invalidated.append(key),
    )
    remembered: list[tuple[Any, ...]] = []
    monkeypatch.setattr(
        users_cache, "remember_identity", lambda *args: remembered.append(args)
    )

    result = await refresh.sync_user_identity(object(), 7)

    assert result == ("", None, None)
    assert invalidated == [7]
    assert remembered == []


@pytest.mark.asyncio
async def test_a_refused_identity_write_is_not_cached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A guard refusal leaves the erased values as the view result."""
    monkeypatch.setattr(users_cache, "get_user", AsyncMock(return_value=None))

    async def _live(*_args: Any) -> tuple[str, str | None, str | None]:
        return "Recovered Name", "recovered", None

    monkeypatch.setattr(refresh, "_fetch_live_identity", _live)
    monkeypatch.setattr(users_cache, "upsert_user", AsyncMock(return_value=False))
    remembered: list[tuple[Any, ...]] = []
    monkeypatch.setattr(
        users_cache, "remember_identity", lambda *args: remembered.append(args)
    )

    result = await refresh.sync_user_identity(object(), 9)

    assert result == ("", None, None)
    assert remembered == []


@pytest.mark.asyncio
async def test_a_display_name_refusal_does_not_rewarm_the_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A refused display-name write must not restore the harvested name."""

    async def _peek(_self: Any, _key: Any) -> list[str | None]:
        return ["Old", "handle", None]

    monkeypatch.setattr(type(user_mention_cache), "peek", _peek)
    monkeypatch.setattr(users_cache, "upsert_user", AsyncMock(return_value=False))
    invalidated: list[int] = []
    puts: list[tuple[Any, ...]] = []
    monkeypatch.setattr(
        type(user_mention_cache),
        "invalidate",
        lambda _self, key: invalidated.append(key),
    )
    monkeypatch.setattr(
        type(user_mention_cache), "put", lambda _self, *args: puts.append(args)
    )

    written = await users_cache.refresh_display_name(11, "Recovered")

    assert written is False
    assert invalidated == [11]
    assert puts == []


@pytest.mark.asyncio
async def test_the_erasure_guard_refusal_is_reported_to_callers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """upsert_user returns False instead of caching a rejected identity."""

    async def _refused(*_args: Any) -> None:
        raise IntegrityError(
            "INSERT",
            {},
            SimpleNamespace(
                diag=SimpleNamespace(
                    constraint_name="ck_telegram_users_erased_identity"
                )
            ),
        )

    monkeypatch.setattr(users_cache, "db_call", _refused)
    invalidated: list[int] = []
    puts: list[tuple[Any, ...]] = []
    monkeypatch.setattr(
        type(user_mention_cache),
        "invalidate",
        lambda _self, key: invalidated.append(key),
    )
    monkeypatch.setattr(
        type(user_mention_cache), "put", lambda _self, *args: puts.append(args)
    )

    written = await users_cache.upsert_user(13, "recovered", "Recovered")

    assert written is False
    assert invalidated == [13]
    assert puts == []


@pytest.mark.asyncio
async def test_membership_harvest_skips_erased_accounts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Erasure removes membership rows; the harvest must not restore them."""
    compiled: list[str] = []

    async def _run(statement: Any) -> None:
        compiled.append(str(statement.compile(dialect=postgresql.dialect())))

    async def _db_call(factory: Any) -> None:
        await factory()

    monkeypatch.setattr(users_cache, "run", _run)
    monkeypatch.setattr(users_cache, "db_call", _db_call)

    await users_cache.touch_chat_member(-100, 42)

    assert len(compiled) == 1
    assert "INSERT INTO chat_members" in compiled[0]
    assert "telegram_users.erased_at IS NOT NULL" in compiled[0]
    assert "ON CONFLICT (chat_id, user_id) DO UPDATE" in compiled[0]


@pytest.mark.asyncio
async def test_an_erasure_during_a_profile_write_wins_the_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A write that resumes after invalidation must not repopulate the cache."""

    async def _db_call(factory: Any) -> None:
        await factory()
        # * The erasure sweep commits and invalidates while this write awaits.
        user_mention_cache.invalidate(42)

    puts: list[tuple[Any, ...]] = []
    monkeypatch.setattr(users_cache, "run", AsyncMock())
    monkeypatch.setattr(users_cache, "db_call", _db_call)
    monkeypatch.setattr(
        type(user_mention_cache), "put", lambda _self, *args: puts.append(args)
    )

    written = await users_cache.upsert_user(42, "handle", "Recovered", "Name")

    assert written is True
    assert puts == []
