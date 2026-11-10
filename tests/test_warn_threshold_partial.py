# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Warn-threshold ban: the warn slate is cleared only where the ban landed."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from telegram.error import BadRequest

from tcbot import database as db
from tcbot.modules.helper.pipelines import warn_flow

_GROUPS: list[dict[str, Any]] = [
    {"chat_id": -1001, "title": "A"},
    {"chat_id": -1002, "title": "B"},
]


def _install(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Record which warn-clear helper the flow calls."""
    calls: dict[str, Any] = {"all": [], "chats": []}

    async def _clear_all(user_id: int) -> int:
        calls["all"].append(user_id)
        return 0

    async def _clear_chats(user_id: int, chat_ids: Any) -> int:
        calls["chats"].append((user_id, list(chat_ids)))
        return 0

    monkeypatch.setattr(db.warns_db, "clear_all_warns", _clear_all)
    monkeypatch.setattr(db.warns_db, "clear_warns_for_chats", _clear_chats)
    return calls


def test_complete_enforcement_clears_the_whole_slate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A ban that reached every group clears every warning."""
    calls = _install(monkeypatch)
    asyncio.run(warn_flow._clear_warns_after_threshold_ban(42, _GROUPS, [None, None]))
    assert calls["all"] == [42]
    assert calls["chats"] == []


def test_partial_enforcement_clears_only_the_reached_groups(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A ban that missed a group must keep that group's warnings."""
    calls = _install(monkeypatch)
    asyncio.run(
        warn_flow._clear_warns_after_threshold_ban(
            42, _GROUPS, [None, RuntimeError("network down")]
        )
    )
    assert calls["all"] == []
    assert calls["chats"] == [(42, [-1001])]


def test_partial_enforcement_ignores_benign_refusals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A user-not-in-chat refusal is not a failed enforcement."""
    calls = _install(monkeypatch)
    benign = _benign_bad_request()
    asyncio.run(warn_flow._clear_warns_after_threshold_ban(42, _GROUPS, [None, benign]))
    assert calls["all"] == [42]
    assert calls["chats"] == []


def _benign_bad_request() -> BaseException:
    """Return a Telegram refusal that counts as benign."""
    return BadRequest("User not participant")
