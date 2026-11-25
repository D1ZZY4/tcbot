# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""The error reporter decides before it schedules, and its dedupe map stays bounded."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import pytest

from tcbot import error_reporter


def _record(message: str = "boom") -> logging.LogRecord:
    """Return a log record the reporter can classify."""
    return logging.LogRecord(
        name="tcbot.test",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg=message,
        args=(),
        exc_info=None,
    )


@pytest.fixture(autouse=True)
def _clean_reporter_state() -> Any:
    """Reset the dedupe map and the owner budget around every test."""
    error_reporter._recent.clear()
    error_reporter._owner_sent.clear()
    yield
    error_reporter._recent.clear()
    error_reporter._owner_sent.clear()


def test_a_duplicate_record_is_reported_once() -> None:
    """The dedupe window still collapses a recurring failure."""
    first = error_reporter._fingerprint_record(_record())
    second = error_reporter._fingerprint_record(_record())

    assert error_reporter._seen_recently(first) is False
    assert error_reporter._seen_recently(second) is True


def test_the_dedupe_map_stays_bounded() -> None:
    """The map is capped, so an incident cannot grow it without bound."""
    for index in range(error_reporter._RECENT_MAX + 200):
        error_reporter._seen_recently(("exc", f"error-{index}"))

    assert len(error_reporter._recent) <= error_reporter._RECENT_MAX


def test_owner_dedupe_map_stays_bounded_when_all_entries_are_fresh() -> None:
    """A flood of distinct fingerprints evicts the oldest tenth, not nothing."""
    for index in range(error_reporter._OWNER_MAX + 200):
        error_reporter._owner_suppressed(("exc", f"conflict-{index}"))

    assert len(error_reporter._owner_sent) <= error_reporter._OWNER_MAX


def test_suppressed_sightings_do_not_extend_the_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A frequent failure must re-report after the window, not be silenced."""
    clock = {"now": 1000.0}
    monkeypatch.setattr(error_reporter, "monotonic", lambda: clock["now"])
    fingerprint = ("exc", "recurring")

    assert error_reporter._seen_recently(fingerprint) is False
    first_report_at = error_reporter._recent[fingerprint]

    clock["now"] += 10
    assert error_reporter._seen_recently(fingerprint) is True
    assert error_reporter._recent[fingerprint] == first_report_at

    clock["now"] += 20
    assert error_reporter._seen_recently(fingerprint) is True
    assert error_reporter._recent[fingerprint] == first_report_at

    clock["now"] += 1
    assert error_reporter._seen_recently(fingerprint) is False
    assert error_reporter._recent[fingerprint] == first_report_at + 31


def test_an_expired_fingerprint_is_reported_again() -> None:
    """A failure outside the window ships again."""
    fingerprint = ("exc", "recurring")

    assert error_reporter._seen_recently(fingerprint) is False
    assert error_reporter._seen_recently(fingerprint) is True

    # * Age every entry past the window: the next sighting is a new one.
    for key in list(error_reporter._recent):
        error_reporter._recent[key] -= error_reporter._DEDUPE_WINDOW * 2

    assert error_reporter._seen_recently(fingerprint) is False


class _FakeTracker:
    """Stand-in for the reporter's task tracker."""

    def __init__(self) -> None:
        self.spawned: list[Any] = []

    def spawn(self, coro: Any) -> bool:
        """Record the scheduled coroutine instead of running it."""
        self.spawned.append(coro)
        coro.close()
        return True


def test_a_duplicate_record_never_reaches_the_sink(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The decision happens before the delivery task is created.

    One task per error line would put the task creation on the event loop
    exactly when an incident floods it, and most error lines are
    duplicates that never ship.
    """
    tracker = _FakeTracker()
    monkeypatch.setattr(error_reporter, "_report_tasks", tracker)
    monkeypatch.setattr(error_reporter, "_bot", object())

    record = _record()
    error_reporter._schedule_record(record)
    error_reporter._schedule_record(record)

    assert len(tracker.spawned) == 1


def test_a_worker_thread_record_reaches_the_attached_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A log record from the Flask thread must still reach the error channel.

    ``TaskTracker.spawn`` needs a running loop, which a worker thread does
    not have; the reporter hands that delivery to the attached loop.
    """
    delivered: list[str] = []

    async def _ship(record: logging.LogRecord) -> None:
        delivered.append(record.getMessage())

    async def _run() -> None:
        error_reporter._loop = asyncio.get_running_loop()
        monkeypatch.setattr(error_reporter, "_ship_record", _ship)
        monkeypatch.setattr(error_reporter, "_bot", object())
        await asyncio.to_thread(error_reporter._schedule_record, _record("thread"))
        await asyncio.gather(
            *[
                asyncio.wrap_future(future)
                for future in list(error_reporter._cross_thread)
            ]
        )

    try:
        asyncio.run(_run())
    finally:
        error_reporter._loop = None
        error_reporter._cross_thread.clear()

    assert delivered == ["thread"]
