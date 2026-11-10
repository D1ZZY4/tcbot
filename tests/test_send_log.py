# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""The federation log delivery contract."""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest

from tcbot import cfg
from tcbot.modules.helper.messages import safe_edits, send_log


class _FakeBot:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []

    async def send_message(self, chat_id: int, text: str, **kwargs: Any) -> Any:
        self.calls.append((chat_id, text, kwargs))
        return type("M", (), {"message_id": 1})()


@pytest.fixture
def _logs_destination(monkeypatch: pytest.MonkeyPatch) -> tuple[int, int]:
    """Point the federation log destination at a known chat and thread."""
    destination = (-1001234567890, 42)
    monkeypatch.setattr(safe_edits, "cfg", dataclasses.replace(cfg, logs=destination))
    return destination


async def test_send_log_posts_to_the_configured_destination(
    _logs_destination: tuple[int, int],
) -> None:
    """The log must land in the configured chat and thread."""
    bot = _FakeBot()
    await send_log(
        bot,  # type: ignore[arg-type]
        "audit text",
    )

    assert len(bot.calls) == 1
    chat_id, text, kwargs = bot.calls[0]
    assert chat_id == _logs_destination[0]
    assert text == "audit text"
    assert kwargs["message_thread_id"] == _logs_destination[1]
    assert kwargs["parse_mode"] == "MarkdownV2"


async def test_send_log_forwards_extra_keyword_arguments(
    _logs_destination: tuple[int, int],
) -> None:
    """A keyboard on the log post must reach Telegram unchanged."""
    bot = _FakeBot()
    await send_log(
        bot,  # type: ignore[arg-type]
        "audit text",
        reply_markup="KB",
    )

    assert bot.calls[0][2]["reply_markup"] == "KB"


async def test_send_log_does_not_duplicate_the_parse_mode(
    _logs_destination: tuple[int, int],
) -> None:
    """The helper owns the parse mode, so a caller cannot override it."""
    bot = _FakeBot()
    with pytest.raises(TypeError):
        await send_log(
            bot,  # type: ignore[arg-type]
            "audit text",
            parse_mode="HTML",
        )
