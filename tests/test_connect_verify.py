# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Bot-added verification walks the three membership requirements, then confirms."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from tcbot.modules.helper.pipelines import connect_verify, connected_flow


def test_verify_keyboard_advances_then_connects() -> None:
    flow = connected_flow.BuildConnection("TCF")
    for step in (0, 1, 2):
        markup = flow.verify_keyboard(step, "en-US")
        callbacks = [
            button.callback_data for row in markup.inline_keyboard for button in row
        ]
        assert callbacks[0] == f"tc_verify_{step + 1}"
        assert callbacks[1] == "tc_cancel"
    final = flow.verify_keyboard(3, "en-US")
    callbacks = [
        button.callback_data for row in final.inline_keyboard for button in row
    ]
    assert callbacks == ["tc_join", "tc_cancel"]


def test_verify_prompt_shows_requirements_then_confirmation() -> None:
    flow = connected_flow.BuildConnection("TCF")
    for step, marker in enumerate(("1.", "2.", "3.")):
        text = flow.verify_prompt(step, "en-US")
        assert "Membership requirements" in text
        assert marker in text
    final = flow.verify_prompt(3, "en-US")
    assert "confirmed all three requirements" in final


def test_non_owner_cannot_advance_the_verification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    alerts: list[str] = []

    async def _alert(query: Any, text: str, **kwargs: Any) -> None:
        alerts.append(text)

    async def _locale(update: Any) -> str:
        return "en-US"

    monkeypatch.setattr(connect_verify, "answer_alert", _alert)
    monkeypatch.setattr(connect_verify, "locale_for_update", _locale)

    class _Query:
        data = "tc_verify_1"

        async def answer(self, *args: Any, **kwargs: Any) -> None:
            return None

    class _Bot:
        async def get_chat_member(self, chat_id: int, user_id: int) -> Any:
            return SimpleNamespace(status="member")

    flow = connected_flow.BuildConnection("TCF")
    update = SimpleNamespace(
        callback_query=_Query(),
        effective_chat=SimpleNamespace(id=-1001),
        effective_user=SimpleNamespace(id=11),
    )
    ctx = SimpleNamespace(bot=_Bot())

    asyncio.run(flow.on_verify_step(update, ctx))  # type: ignore[arg-type]

    assert alerts and "only" in alerts[0].lower()
