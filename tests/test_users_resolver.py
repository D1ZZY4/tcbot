# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""Tests for tcbot.modules.helper.extraction - UserIdentity and resolve_identity."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from telegram.error import TelegramError

from tcbot.modules.helper import extraction
from tcbot.modules.helper.extraction import UserIdentity, resolve_identity


def _ctx(get_chat: AsyncMock) -> SimpleNamespace:
    return SimpleNamespace(bot=SimpleNamespace(get_chat=get_chat))


# ────────────────────────── UserIdentity ────────────────────────── #


def test_user_identity_name_with_username_combines() -> None:
    ident = UserIdentity(user_id=1, display_name="Andi", username="andi")
    assert ident.name_with_username == "Andi (@andi)"


def test_user_identity_name_with_username_returns_display_only_when_no_username() -> (
    None
):
    ident = UserIdentity(user_id=1, display_name="Andi", username=None)
    assert ident.name_with_username == "Andi"


def test_user_identity_is_frozen_dataclass() -> None:
    ident = UserIdentity(user_id=1, display_name="Andi", username=None)
    with pytest.raises((AttributeError, TypeError)):
        setattr(ident, "display_name", "Changed")


# ────────────────── resolve_identity - live path ────────────────── #


async def test_resolve_identity_uses_get_chat_first_name() -> None:
    chat = SimpleNamespace(first_name="Andi", title=None, username="andi")
    ident = await resolve_identity(_ctx(AsyncMock(return_value=chat)), 42)
    assert ident == UserIdentity(user_id=42, display_name="Andi", username="andi")


async def test_resolve_identity_uses_title_when_no_first_name() -> None:
    chat = SimpleNamespace(first_name=None, title="My Group", username=None)
    ident = await resolve_identity(_ctx(AsyncMock(return_value=chat)), 99)
    assert ident.display_name == "My Group"


# ──────────────── resolve_identity - cache fallback ─────────────── #


async def test_resolve_identity_falls_back_to_cache_on_telegram_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ctx = _ctx(AsyncMock(side_effect=TelegramError("forbidden")))
    monkeypatch.setattr(
        extraction.members_repo,
        "find_latest_for_user",
        AsyncMock(return_value={"first_name": "Citra", "username": "citra"}),
    )
    ident = await resolve_identity(ctx, 99)
    assert ident == UserIdentity(user_id=99, display_name="Citra", username="citra")


async def test_resolve_identity_uses_username_from_cache_when_no_first_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ctx = _ctx(AsyncMock(side_effect=TelegramError("unreachable")))
    monkeypatch.setattr(
        extraction.members_repo,
        "find_latest_for_user",
        AsyncMock(return_value={"first_name": None, "username": "fromcache"}),
    )
    ident = await resolve_identity(ctx, 12)
    assert ident.username == "fromcache"
    assert ident.display_name == "@fromcache"


# ────────────── resolve_identity - ultimate fallback ────────────── #


async def test_resolve_identity_ultimate_fallback_uses_str_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ctx = _ctx(AsyncMock(side_effect=TelegramError("gone")))
    monkeypatch.setattr(
        extraction.members_repo,
        "find_latest_for_user",
        AsyncMock(return_value=None),
    )
    ident = await resolve_identity(ctx, 7)
    assert ident == UserIdentity(user_id=7, display_name="7", username=None)


async def test_resolve_identity_skips_chat_with_blank_names_to_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    blank = SimpleNamespace(first_name=None, title=None, username=None)
    ctx = _ctx(AsyncMock(return_value=blank))
    monkeypatch.setattr(
        extraction.members_repo,
        "find_latest_for_user",
        AsyncMock(return_value={"first_name": "Dani", "username": None}),
    )
    ident = await resolve_identity(ctx, 55)
    assert ident.display_name == "Dani"
