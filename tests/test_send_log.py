# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""The federation log delivery contract."""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from tcbot import cfg
from tcbot.modules.helper.messages import send_log
from tcbot.modules.helper.rich import edit_msg as rich_edit


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
    monkeypatch.setattr(rich_edit, "cfg", dataclasses.replace(cfg, logs=destination))
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
    assert "parse_mode" not in kwargs


async def test_send_log_forwards_extra_keyword_arguments(
    _logs_destination: tuple[int, int],
) -> None:
    """A keyboard on the log post must reach Telegram unchanged."""
    markup = InlineKeyboardMarkup([[InlineKeyboardButton("Go", callback_data="go")]])
    bot = _FakeBot()
    await send_log(
        bot,  # type: ignore[arg-type]
        "audit text",
        reply_markup=markup,
    )

    assert '<tg-button type="callback_data"' in bot.calls[0][1]


async def test_send_log_does_not_duplicate_the_parse_mode(
    _logs_destination: tuple[int, int],
) -> None:
    """A caller cannot force a parse mode onto the rich log delivery."""
    bot = _FakeBot()
    await send_log(
        bot,  # type: ignore[arg-type]
        "audit text",
        parse_mode="HTML",
    )
    assert "parse_mode" not in bot.calls[0][2]
