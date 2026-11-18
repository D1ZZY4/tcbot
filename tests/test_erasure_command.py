# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""The Founder-facing erasure command queues one request."""

from __future__ import annotations

import asyncio
import inspect
from types import SimpleNamespace
from typing import Any

import pytest

from tcbot.modules import maintenance


class _Message:
    def __init__(self, text: str) -> None:
        self.text = text
        self.replies: list[str] = []

    async def reply_text(self, text: str, **kwargs: Any) -> None:
        self.replies.append(text)


def test_tcforget_queues_the_request(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[tuple[int, str]] = []

    async def _request(user_id: int, reason: str) -> int:
        seen.append((user_id, reason))
        return 5

    async def _locale(update: Any) -> str:
        return "en-US"

    async def _owner(*, fresh: bool = False) -> int:
        return 1

    monkeypatch.setattr(maintenance.db.erasure_db, "request_erasure", _request)
    monkeypatch.setattr(maintenance.db.users_roles, "get_owner_id", _owner)
    monkeypatch.setattr(maintenance, "locale_for_update", _locale)

    message = _Message("/tcforget 123 spam account")
    update = SimpleNamespace(effective_message=message)
    asyncio.run(inspect.unwrap(maintenance.cmd_forget)(update, None))

    assert seen == [(123, "spam account")]
    assert message.replies
    assert "5" in message.replies[-1]


def test_tcforget_rejects_a_missing_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _request(user_id: int, reason: str) -> int:
        raise AssertionError("a malformed command must not queue anything")

    async def _locale(update: Any) -> str:
        return "en-US"

    async def _owner(*, fresh: bool = False) -> int:
        return 1

    monkeypatch.setattr(maintenance.db.erasure_db, "request_erasure", _request)
    monkeypatch.setattr(maintenance.db.users_roles, "get_owner_id", _owner)
    monkeypatch.setattr(maintenance, "locale_for_update", _locale)

    message = _Message("/tcforget 123")
    update = SimpleNamespace(effective_message=message)
    asyncio.run(inspect.unwrap(maintenance.cmd_forget)(update, None))

    assert message.replies


def test_tcforget_refuses_the_current_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Founder cannot erase the account that holds the owner role."""
    queued: list[int] = []

    async def _request(user_id: int, reason: str) -> int:
        queued.append(user_id)
        return 5

    async def _owner(*, fresh: bool = False) -> int:
        return 123

    async def _locale(update: Any) -> str:
        return "en-US"

    monkeypatch.setattr(maintenance.db.erasure_db, "request_erasure", _request)
    monkeypatch.setattr(maintenance.db.users_roles, "get_owner_id", _owner)
    monkeypatch.setattr(maintenance, "locale_for_update", _locale)

    message = _Message("/tcforget 123 spam account")
    update = SimpleNamespace(effective_message=message)
    asyncio.run(inspect.unwrap(maintenance.cmd_forget)(update, None))

    assert queued == []
    assert message.replies
    assert "owner" in message.replies[-1].lower()
