# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Unowned group text must not trigger editor prompts or permission refusals."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from pyrogram import ContinuePropagation

from tcbot import database as db
from tcbot.modules import stats
from tcbot.modules.helper.handlers import ConversationHandler
from tcbot.modules.helper.pipelines import (
    rules_editor_draft,
    rules_editor_steps,
    stats_panels,
)
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


def test_group_text_without_an_editor_step_passes_through() -> None:
    """An ordinary group message must not get an editor refusal."""
    ctx = _ctx(text="nigawat")
    ctx.user_data = {}

    async def _run() -> None:
        with pytest.raises(ContinuePropagation):
            await rules_editor_draft.rules_draft_editor.on_text(ctx)

    asyncio.run(_run())
    assert ctx.user_data == {}


def test_private_text_without_an_editor_step_passes_through() -> None:
    """A private message with no pending step is not editor input."""
    ctx = _ctx(private=True, text="Ui")
    ctx.user_data = {}

    async def _run() -> None:
        with pytest.raises(ContinuePropagation):
            await rules_editor_draft.rules_draft_editor.on_text(ctx)

    asyncio.run(_run())
    assert ctx.user_data == {}


def test_group_text_with_a_stale_step_still_passes_through() -> None:
    """A leftover editor step must not claim a later group message."""
    ctx = _ctx(text="Ui")
    ctx.user_data = {"rules_step": "item_body"}

    async def _run() -> None:
        with pytest.raises(ContinuePropagation):
            await rules_editor_draft.rules_draft_editor.on_text(ctx)

    asyncio.run(_run())
    assert ctx.user_data == {"rules_step": "item_body"}


def test_a_real_private_step_by_a_non_staff_user_still_refuses(
    monkeypatch: Any,
) -> None:
    """The ownership guard must not weaken the editor permission gate."""
    ctx = _ctx(private=True, text="Ui")
    ctx.user_data = {"rules_step": "item_body"}
    replies: list[Any] = []

    async def _denied(*_args: Any, **_kwargs: Any) -> bool:
        return False

    async def _reply(*args: Any, **kwargs: Any) -> Any:
        _ = kwargs
        replies.append(args)
        return None

    monkeypatch.setattr(db.users_roles, "has_permission", _denied)
    monkeypatch.setattr(rules_editor_draft, "reply_rich", _reply)
    monkeypatch.setattr(rules_editor_steps, "reply_rich", _reply)

    result = asyncio.run(rules_editor_draft.rules_draft_editor.on_text(ctx))

    assert result == ConversationHandler.END
    assert replies


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


def test_a_document_without_an_upload_step_passes_through() -> None:
    """A stray document must not be parsed as a rules import."""
    ctx = _ctx(private=False, document=SimpleNamespace(file_name="notes.md"))
    ctx.user_data = {}

    async def _run() -> None:
        with pytest.raises(ContinuePropagation):
            await rules_editor_draft.rules_draft_editor.on_markdown(ctx)

    asyncio.run(_run())
    assert ctx.user_data == {}
