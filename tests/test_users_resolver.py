# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""Tests for the cross-source identity resolver in :mod:`tgbot_tcf.utils.users`."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from telegram.error import TelegramError

from tgbot_tcf.utils import users
from tgbot_tcf.utils.users import UserIdentity, resolve_identity


def _ctx(get_chat: AsyncMock) -> SimpleNamespace:
    return SimpleNamespace(bot=SimpleNamespace(get_chat=get_chat))


def test_user_identity_name_with_username_combines() -> None:
    ident = UserIdentity(user_id=1, display_name="Andi", username="andi")
    assert ident.name_with_username == "Andi (@andi)"


def test_user_identity_name_with_username_falls_back() -> None:
    ident = UserIdentity(user_id=1, display_name="Andi", username=None)
    assert ident.name_with_username == "Andi"


async def test_resolve_identity_uses_get_chat_when_available() -> None:
    chat = SimpleNamespace(first_name="Andi", title=None, username="andi")
    ctx = _ctx(AsyncMock(return_value=chat))
    ident = await resolve_identity(ctx, 42)
    assert ident == UserIdentity(user_id=42, display_name="Andi", username="andi")


async def test_resolve_identity_falls_back_to_cache_on_telegram_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ctx = _ctx(AsyncMock(side_effect=TelegramError("forbidden")))
    monkeypatch.setattr(
        users.members_repo,
        "find_latest_for_user",
        AsyncMock(return_value={"first_name": "Citra", "username": "citra"}),
    )
    ident = await resolve_identity(ctx, 99)
    assert ident == UserIdentity(user_id=99, display_name="Citra", username="citra")


async def test_resolve_identity_ultimate_fallback_uses_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ctx = _ctx(AsyncMock(side_effect=TelegramError("unreachable")))
    monkeypatch.setattr(
        users.members_repo,
        "find_latest_for_user",
        AsyncMock(return_value=None),
    )
    ident = await resolve_identity(ctx, 7)
    assert ident == UserIdentity(user_id=7, display_name="7", username=None)


async def test_resolve_identity_uses_cache_when_get_chat_returns_blank(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    blank_chat = SimpleNamespace(first_name=None, title=None, username=None)
    ctx = _ctx(AsyncMock(return_value=blank_chat))
    monkeypatch.setattr(
        users.members_repo,
        "find_latest_for_user",
        AsyncMock(return_value={"first_name": None, "username": "fromcache"}),
    )
    ident = await resolve_identity(ctx, 12)
    assert ident.username == "fromcache"
    assert ident.display_name == "@fromcache"
