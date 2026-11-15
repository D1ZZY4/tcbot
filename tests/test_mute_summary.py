# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""The mute outcome names the groups where the restriction did not land."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from tcbot import database as db
from tcbot.modules.helper.pipelines import mute_flow


class _Bot:
    def __init__(self) -> None:
        self.edits: list[str] = []

    async def edit_message_text(self, text: str, **kwargs: Any) -> None:
        self.edits.append(text)

    async def restrict_chat_member(self, *args: Any, **kwargs: Any) -> None:
        return None

    async def send_message(self, *args: Any, **kwargs: Any) -> Any:
        return object()


def test_a_partial_mute_names_the_failed_groups(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    groups = [
        {"chat_id": 1, "title": "Landed"},
        {"chat_id": 2, "title": "Gone"},
    ]

    async def _locale(update: Any) -> str:
        return "en-US"

    async def _no_refusal(*args: Any, **kwargs: Any) -> None:
        return None

    async def _groups() -> list[dict[str, Any]]:
        return groups

    async def _record(*args: Any, **kwargs: Any) -> tuple[int, None]:
        return 1, None

    async def _demote(*args: Any, **kwargs: Any) -> None:
        return None

    async def _fan_out(coros: Any) -> list[object]:
        for coro in coros:
            coro.close()
        return [None, RuntimeError("chat not found")]

    def _summarize(*args: Any, **kwargs: Any) -> Any:
        return SimpleNamespace(
            applied=1,
            total=2,
            failed=1,
            transient=[({"chat_id": 2, "title": "Gone"}, RuntimeError("gone"))],
        )

    async def _send_log(*args: Any, **kwargs: Any) -> None:
        return None

    monkeypatch.setattr(mute_flow, "locale_for_update", _locale)
    monkeypatch.setattr(mute_flow.guards, "enforcement_refusal", _no_refusal)
    monkeypatch.setattr(db.groups_db, "active_groups", _groups)
    monkeypatch.setattr(db.mutes_db, "record_mute", _record)
    monkeypatch.setattr(mute_flow, "demote_before_enforcement", _demote)
    monkeypatch.setattr(mute_flow, "fan_out", _fan_out)
    monkeypatch.setattr(mute_flow, "summarize_fanout", _summarize)
    monkeypatch.setattr(mute_flow, "send_log", _send_log)

    bot = _Bot()
    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=1),
        effective_message=None,
    )
    meta = {
        "mute_target_id": 42,
        "mute_target_fname": "Target",
        "mute_admin_id": 7,
        "mute_admin_fname": "Admin",
        "mute_reason": "spam",
        "mute_duration": None,
        "mute_proof_msgs": None,
        "mute_prompt_chat": 1,
        "mute_prompt_id": 5,
    }

    asyncio.run(mute_flow._execute_mute(bot, update, meta))  # type: ignore[arg-type]

    assert bot.edits
    assert "Gone" in bot.edits[-1]
    assert "WARNING" in bot.edits[-1]
