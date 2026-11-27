# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Unowned group text must not trigger deferred search prompts."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from pyrogram import ContinuePropagation

from tcbot.modules import stats
from tcbot.modules.helper.pipelines import stats_panels
from tcbot.utils.time_and_date import monotonic


def _ctx(*, private: bool = False, document: Any = None, text: str = "Ui") -> Any:
    chat_type = SimpleNamespace(value="private" if private else "supergroup")
    msg = SimpleNamespace(text=text, document=document, chat=SimpleNamespace(id=-100))
    return SimpleNamespace(
        user_data={},
        chat_data={},
        bot_data={},
        args=(),
        bot=None,
        effective_message=msg,
        effective_chat=SimpleNamespace(id=-100, type=chat_type),
        effective_user=SimpleNamespace(id=7, first_name="User"),
        callback_query=None,
    )


def test_stats_search_without_a_prompt_passes_through() -> None:
    """A stale-free scope must not let the deferred search consume text."""
    ctx = _ctx(text="keren jir")
    ctx.user_data = {}

    async def _run() -> None:
        with pytest.raises(ContinuePropagation):
            await stats.on_bans_search_input(ctx)

    asyncio.run(_run())
    assert ctx.user_data == {}


def test_an_expired_stats_prompt_passes_through(monkeypatch: Any) -> None:
    """A prompt left from an earlier panel must not own a later message."""
    ctx = _ctx(text="keren jir")
    ctx.user_data = {
        stats_panels.SEARCH_KEY: True,
        stats_panels.SEARCH_DEADLINE_KEY: monotonic() - 1,
        stats_panels.CHAT_KEY: -100,
        stats_panels.MSG_KEY: 5,
    }
    deleted: list[Any] = []

    async def _delete() -> None:
        deleted.append(True)

    ctx.effective_message.delete = _delete

    async def _run() -> None:
        with pytest.raises(ContinuePropagation):
            await stats.on_bans_search_input(ctx)

    asyncio.run(_run())
    assert ctx.user_data == {}
    assert deleted == []


def test_a_fresh_owned_search_still_runs(monkeypatch: Any) -> None:
    """The expiry guard must not break a real search prompt."""
    calls: list[Any] = []

    async def _staff(*_args: Any, **_kwargs: Any) -> str:
        return "en-US"

    async def _search(query: str) -> list[Any]:
        calls.append(query)
        return []

    async def _delete() -> None:
        calls.append("delete")

    async def _edit(*_args: Any, **_kwargs: Any) -> bool:
        calls.append("edit")
        return True

    monkeypatch.setattr(stats, "_require_staff_input", _staff)
    monkeypatch.setattr(stats.Stats, "search_run", _search)
    monkeypatch.setattr(stats, "safe_edit_message", _edit)
    ctx = _ctx(text="keren jir")
    ctx.effective_message.delete = _delete
    ctx.user_data = {
        stats_panels.SEARCH_KEY: True,
        stats_panels.SEARCH_DEADLINE_KEY: monotonic() + 100,
        stats_panels.CHAT_KEY: -100,
        stats_panels.MSG_KEY: 5,
    }

    asyncio.run(stats.on_bans_search_input(ctx))

    assert calls[0] == "keren jir"
    assert "delete" in calls
    assert stats_panels.SEARCH_KEY not in ctx.user_data
