# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""The send budget must not drop an incident report on a summary failure."""

from __future__ import annotations

import asyncio
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
        return object()


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


class _AlwaysFailingBot:
    """Telegram rejects every send, so no report actually ships."""

    def __init__(self) -> None:
        self.attempts = 0

    async def send_rich_message(
        self, _chat_id: int, _rich_message: Any, **_kwargs: Any
    ) -> None:
        self.attempts += 1
        raise RuntimeError("LOG_ERRORS unavailable")


@pytest.mark.asyncio
async def test_a_failed_report_neither_spends_budget_nor_vanishes_from_the_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A dropped report must stay visible in the rollover count."""
    bot = _AlwaysFailingBot()
    monkeypatch.setattr(error_reporter, "_bot", bot)
    monkeypatch.setattr(error_reporter, "_chat_id", -100)
    monkeypatch.setattr(error_reporter, "_thread_id", None)
    monkeypatch.setattr(error_reporter, "_send_window_start", 10_000.0)
    monkeypatch.setattr(error_reporter, "_sent_in_window", 0)
    monkeypatch.setattr(error_reporter, "_suppressed_in_window", 0)
    monkeypatch.setattr(error_reporter, "monotonic", lambda: 10_001.0)

    await error_reporter._ship_throttled({"html": "first incident"})
    await error_reporter._ship_throttled({"html": "second incident"})

    assert bot.attempts == 2
    assert error_reporter._sent_in_window == 0
    assert error_reporter._suppressed_in_window == 2


class _GatedBot:
    """Hold the first send open so a second report reaches the budget gate."""

    def __init__(self) -> None:
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.calls = 0

    async def send_rich_message(
        self, _chat_id: int, _rich_message: Any, **_kwargs: Any
    ) -> None:
        self.calls += 1
        self.entered.set()
        await self.release.wait()
        return object()


@pytest.mark.asyncio
async def test_concurrent_reports_reserve_one_slot_each(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two overlapping senders cannot both claim the last free budget slot."""
    bot = _GatedBot()
    monkeypatch.setattr(error_reporter, "_bot", bot)
    monkeypatch.setattr(error_reporter, "_chat_id", -100)
    monkeypatch.setattr(error_reporter, "_thread_id", None)
    monkeypatch.setattr(error_reporter, "_send_window_start", 10_000.0)
    monkeypatch.setattr(error_reporter, "_sent_in_window", 19)
    monkeypatch.setattr(error_reporter, "_suppressed_in_window", 0)
    monkeypatch.setattr(error_reporter, "monotonic", lambda: 10_001.0)

    first = asyncio.create_task(error_reporter._ship_throttled({"html": "first"}))
    await asyncio.wait_for(bot.entered.wait(), timeout=1)
    second = asyncio.create_task(error_reporter._ship_throttled({"html": "second"}))
    for _ in range(10):
        await asyncio.sleep(0)
    assert bot.calls == 1

    bot.release.set()
    await asyncio.gather(first, second)
    assert bot.calls == 1
    assert error_reporter._sent_in_window == 20
    assert error_reporter._suppressed_in_window == 1


@pytest.mark.asyncio
async def test_failed_summary_restores_its_suppressed_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed rollover send keeps the incident count it was reporting."""
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
    assert bot.calls[1] == "current incident"
    assert error_reporter._sent_in_window == 1
    assert error_reporter._suppressed_in_window == 3


class _StallingBot:
    """Fail the first send only after a second window has already started."""

    def __init__(self) -> None:
        self.first_started = asyncio.Event()
        self.release_first = asyncio.Event()
        self.calls = 0

    async def send_rich_message(
        self, _chat_id: int, _rich_message: Any, **_kwargs: Any
    ) -> Any:
        self.calls += 1
        if self.calls == 1:
            self.first_started.set()
            await self.release_first.wait()
            raise RuntimeError("send failed after rollover")
        return object()


@pytest.mark.asyncio
async def test_a_failed_send_does_not_refund_the_next_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A late failure must not decrement a different window's counter."""
    bot = _StallingBot()
    clock = [10_001.0]
    monkeypatch.setattr(error_reporter, "_bot", bot)
    monkeypatch.setattr(error_reporter, "_chat_id", -100)
    monkeypatch.setattr(error_reporter, "_thread_id", None)
    monkeypatch.setattr(error_reporter, "_send_window_start", 10_000.0)
    monkeypatch.setattr(error_reporter, "_sent_in_window", 0)
    monkeypatch.setattr(error_reporter, "_suppressed_in_window", 0)
    monkeypatch.setattr(error_reporter, "monotonic", lambda: clock[0])

    first = asyncio.create_task(error_reporter._ship_throttled({"html": "first"}))
    await asyncio.wait_for(bot.first_started.wait(), timeout=1)
    clock[0] = 10_070.0
    await error_reporter._ship_throttled({"html": "second"})
    bot.release_first.set()
    await first

    assert bot.calls == 2
    assert error_reporter._sent_in_window == 1
    assert error_reporter._suppressed_in_window == 1
