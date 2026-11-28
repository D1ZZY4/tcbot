# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Regression coverage for bounded task draining and mention fallbacks."""

from __future__ import annotations

import asyncio
import contextlib
from datetime import timedelta

import pytest

from tcbot.utils.i18n import user_ref
from tcbot.utils.tasks import TaskTracker
from tcbot.utils.time_and_date import parse_duration


async def test_drain_is_bounded_when_a_task_suppresses_cancellation() -> None:
    """A task that swallows one cancel must not hang shutdown forever."""
    tracker = TaskTracker("test")

    async def stubborn() -> None:
        # * One swallowed cancellation is exactly the case that made the old
        # * wait_for(gather(...)) wait past its own timeout.
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.sleep(60)
        await asyncio.sleep(60)

    tracker.spawn(stubborn())
    await asyncio.sleep(0)
    try:
        await asyncio.wait_for(tracker.drain(timeout=0.05), timeout=1)
    except TimeoutError:
        raise AssertionError("TaskTracker.drain exceeded its own budget") from None


async def test_drain_cancels_pending_tasks_when_the_drain_itself_is_cancelled() -> None:
    """A cancellation during the drain must not strand tracked work."""
    tracker = TaskTracker("double-cancel")
    started = asyncio.Event()

    async def slow() -> None:
        started.set()
        await asyncio.sleep(30)

    tracker.spawn(slow())
    await started.wait()
    drain = asyncio.create_task(tracker.drain(timeout=0.05))
    await asyncio.sleep(0)
    drain.cancel()

    with pytest.raises(asyncio.CancelledError):
        await drain
    assert tracker.pending == 0


def test_user_ref_without_a_name_uses_the_numeric_id() -> None:
    """A missing name must render the ID, never the literal text 'None'."""
    assert user_ref(12345, None) == "12345"  # type: ignore[arg-type]


def test_short_durations_are_clamped_to_a_safe_restriction_floor() -> None:
    """Sub-30-second mutes must not become permanent on Telegram."""
    # * Telegram treats a restriction shorter than 30 seconds as forever.
    # * The stored expiry and the Bot API until_date must agree.
    assert parse_duration("10s") == timedelta(seconds=60)
    assert parse_duration("29s") == timedelta(seconds=60)
    assert parse_duration("90s") == timedelta(seconds=90)
    assert parse_duration("0s") is None
