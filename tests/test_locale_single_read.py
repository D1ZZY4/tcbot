# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Locale resolution reads only the locale the chat type consumes."""

from __future__ import annotations

import asyncio

import pytest

from tcbot.database import groups_db, settings_db
from tcbot.modules.helper.locale import effective_locale
from tcbot.utils.i18n import DEFAULT_LOCALE


def _counted(
    monkeypatch: pytest.MonkeyPatch,
    *,
    user_locale: str | None = None,
    group_locale: str | None = None,
) -> dict[str, int]:
    """Stub both locale reads and return a call-count dict."""
    calls = {"user": 0, "group": 0}

    async def fake_user(_user_id: int) -> str | None:
        calls["user"] += 1
        return user_locale

    async def fake_group(_chat_id: int) -> str | None:
        calls["group"] += 1
        return group_locale

    monkeypatch.setattr(settings_db, "get_user_locale", fake_user)
    monkeypatch.setattr(groups_db, "get_group_locale", fake_group)
    return calls


def test_private_reads_only_user_locale(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _counted(monkeypatch, user_locale="en-US")

    assert asyncio.run(effective_locale("private", 7, -100)) == "en-US"
    assert calls == {"user": 1, "group": 0}


def test_group_reads_only_group_locale(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _counted(monkeypatch, group_locale="en-US")

    assert asyncio.run(effective_locale("supergroup", 7, -100)) == "en-US"
    assert calls == {"user": 0, "group": 1}


def test_private_failure_falls_back_without_group_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def boom(_id: int) -> str | None:
        raise RuntimeError("db down")

    async def must_not_run(_id: int) -> str | None:
        raise AssertionError("group read must be skipped for private chats")

    monkeypatch.setattr(settings_db, "get_user_locale", boom)
    monkeypatch.setattr(groups_db, "get_group_locale", must_not_run)

    assert asyncio.run(effective_locale("private", 7, -100)) == DEFAULT_LOCALE


def test_group_failure_falls_back_without_user_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def boom(_id: int) -> str | None:
        raise RuntimeError("db down")

    async def must_not_run(_id: int) -> str | None:
        raise AssertionError("user read must be skipped for group chats")

    monkeypatch.setattr(settings_db, "get_user_locale", must_not_run)
    monkeypatch.setattr(groups_db, "get_group_locale", boom)

    assert asyncio.run(effective_locale("group", 7, -100)) == DEFAULT_LOCALE


def test_none_chat_type_reads_user_locale(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _counted(monkeypatch, user_locale="en-US")

    assert asyncio.run(effective_locale(None, 7, -100)) == "en-US"
    assert calls == {"user": 1, "group": 0}


def test_cancellation_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    async def cancelled(_id: int) -> str | None:
        raise asyncio.CancelledError()

    monkeypatch.setattr(settings_db, "get_user_locale", cancelled)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(effective_locale("private", 7, -100))
