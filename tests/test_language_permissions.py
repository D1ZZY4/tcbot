# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Group language callbacks: re-rendering the panel needs group permission."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from tcbot.modules import language
from tcbot.modules.helper.decorators import ratelimit


class _Query:
    """Callback-query double that records every answer."""

    def __init__(self, data: str) -> None:
        self.data = data
        self.answers: list[tuple[str | None, dict[str, Any]]] = []

    async def answer(self, text: str | None = None, **kwargs: Any) -> None:
        # * One answer per query, like Telegram itself.
        if self.answers:
            raise RuntimeError("callback query answered twice")
        self.answers.append((text, kwargs))


def _update(data: str) -> Any:
    """Return an update for a group callback from one user."""
    return SimpleNamespace(
        effective_user=SimpleNamespace(id=42),
        effective_chat=SimpleNamespace(id=-100, type="supergroup"),
        callback_query=_Query(data),
    )


@pytest.fixture(autouse=True)
def _bypass_throttle(monkeypatch: pytest.MonkeyPatch) -> None:
    """Exempt the test user from the rate limiter without a database read."""

    async def _exempt(user_id: int) -> bool:
        _ = user_id
        return True

    monkeypatch.setattr(ratelimit, "_is_exempt", _exempt)


def test_group_list_requires_manage_permission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A non-manager cannot re-render another manager's group panel."""
    edited: list[Any] = []

    async def _denied(*args: Any, **kwargs: Any) -> bool:
        _ = (args, kwargs)
        return False

    async def _locale(*args: Any, **kwargs: Any) -> str:
        _ = (args, kwargs)
        return "en-US"

    async def _edit(*args: Any, **kwargs: Any) -> None:
        edited.append((args, kwargs))

    monkeypatch.setattr(language, "can_manage_group", _denied)
    monkeypatch.setattr(language, "effective_locale", _locale)
    monkeypatch.setattr(language, "safe_edit_cb", _edit)

    update = _update("lang:list:group")
    asyncio.run(language.on_lang_list(update, SimpleNamespace(bot=object())))

    assert edited == []
    text, kwargs = update.callback_query.answers[0]
    assert text is not None and "group owner or staff" in text
    assert kwargs.get("show_alert") is True


def test_group_list_renders_for_a_manager(monkeypatch: pytest.MonkeyPatch) -> None:
    """The manager still reaches the list after the permission check."""

    async def _allowed(*args: Any, **kwargs: Any) -> bool:
        _ = (args, kwargs)
        return True

    async def _locale(*args: Any, **kwargs: Any) -> str:
        _ = (args, kwargs)
        return "en-US"

    async def _edit(*args: Any, **kwargs: Any) -> None:
        _ = (args, kwargs)

    monkeypatch.setattr(language, "can_manage_group", _allowed)
    monkeypatch.setattr(language, "effective_locale", _locale)
    monkeypatch.setattr(language, "safe_edit_cb", _edit)

    update = _update("lang:list:group")
    asyncio.run(language.on_lang_list(update, SimpleNamespace(bot=object())))

    assert update.callback_query.answers
    assert update.callback_query.answers[0][1].get("show_alert") is not True


def test_group_save_denial_alerts_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """The denied save must show its alert; a second answer would swallow it."""

    async def _denied(*args: Any, **kwargs: Any) -> bool:
        _ = (args, kwargs)
        return False

    async def _locale(*args: Any, **kwargs: Any) -> str:
        _ = (args, kwargs)
        return "en-US"

    monkeypatch.setattr(language, "can_manage_group", _denied)
    monkeypatch.setattr(language, "effective_locale", _locale)

    update = _update("lang:set:group:en-US")
    update.effective_message = SimpleNamespace()
    asyncio.run(language.on_lang_set(update, SimpleNamespace(bot=object())))

    assert len(update.callback_query.answers) == 1
    text, kwargs = update.callback_query.answers[0]
    assert text is not None and "group owner or staff" in text
    assert kwargs.get("show_alert") is True
