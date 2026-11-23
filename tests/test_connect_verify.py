# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Bot-added verification walks three requirements, the moderation scope, then confirms."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from tcbot.modules.helper.pipelines import connect_added, connect_verify


def test_verify_keyboard_navigates_then_connects() -> None:
    flow = connect_added.BuildConnection("TCF")
    for step in (0, 1, 2, 3, 4):
        markup = flow.verify_keyboard(step, "en-US")
        navigation = [button.callback_data for button in markup.inline_keyboard[0]]
        expected = ([f"tc_verify_{step - 1}"] if step > 0 else []) + [
            f"tc_verify_{step + 1}"
        ]
        assert navigation == expected
        assert [b.callback_data for b in markup.inline_keyboard[1]] == ["tc_cancel"]
    final = flow.verify_keyboard(5, "en-US")
    navigation = [button.callback_data for button in final.inline_keyboard[0]]
    assert navigation == ["tc_verify_4", "tc_join"]
    assert [b.callback_data for b in final.inline_keyboard[1]] == ["tc_cancel"]


def test_verify_prompt_shows_requirements_scope_then_confirmation() -> None:
    flow = connect_added.BuildConnection("TCF")
    welcome = flow.verify_prompt(0, "en-US")
    assert "Connected to TCF" in welcome
    assert "What we will check together" in welcome
    assert "<ul>" in welcome
    for step in (1, 2, 3, 4, 5):
        text = flow.verify_prompt(step, "en-US")
        assert "<h2>" in text
        assert "<hr/>" in text
        assert "<p>" in text
        assert "<details" in text and "Why this matters" in text
    scope = flow.verify_prompt(4, "en-US")
    assert "Federation bans and mutes" in scope
    assert "Warnings stay in the group" in scope
    final = flow.verify_prompt(5, "en-US")
    assert "Ready to connect" in final
    assert "Only the group owner can press Connect" in final


def test_welcome_page_follows_the_reader_locale() -> None:
    """The first-add page uses the localized catalog, not the default text."""
    flow = connect_added.BuildConnection("TCF")
    assert "Connected to TCF" in flow.verify_prompt(0, "en-US")
    assert "Terhubung ke TCF" in flow.verify_prompt(0, "id-ID")


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

    flow = connect_added.BuildConnection("TCF")
    update = SimpleNamespace(
        callback_query=_Query(),
        effective_chat=SimpleNamespace(id=-1001),
        effective_user=SimpleNamespace(id=11),
    )
    ctx = SimpleNamespace(bot=_Bot())

    asyncio.run(flow.on_verify_step(update, ctx))  # type: ignore[arg-type]

    assert alerts and "only" in alerts[0].lower()
