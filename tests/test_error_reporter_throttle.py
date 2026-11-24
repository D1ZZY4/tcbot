# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""The send budget must not drop an incident report on a summary failure."""

from __future__ import annotations

from typing import Any

import pytest

from tcbot import error_reporter


class _FakeBot:
    """Record sends and fail the first one, like a summary hitting a stall."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.fail_first = True

    async def send_rich_message(
        self, _chat_id: int, rich_message: Any, **_kwargs: Any
    ) -> None:
        text = rich_message.html
        self.calls.append(text)
        if self.fail_first and len(self.calls) == 1:
            self.fail_first = False
            raise RuntimeError("summary send stalled")


@pytest.mark.asyncio
async def test_a_failed_summary_still_ships_the_current_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A rollover summary failure does not consume the triggering report."""
    bot = _FakeBot()
    monkeypatch.setattr(error_reporter, "_bot", bot)
    monkeypatch.setattr(error_reporter, "_chat_id", -100)
    monkeypatch.setattr(error_reporter, "_thread_id", None)
    monkeypatch.setattr(error_reporter, "_send_window_start", 0.0)
    monkeypatch.setattr(error_reporter, "_sent_in_window", 0)
    monkeypatch.setattr(error_reporter, "_suppressed_in_window", 3)
    monkeypatch.setattr(error_reporter, "monotonic", lambda: 10_000.0)

    await error_reporter._ship_throttled({"html": "current incident"})

    assert len(bot.calls) == 2
    assert "suppressed" in bot.calls[0]
    assert bot.calls[1] == "current incident"
