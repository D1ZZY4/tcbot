# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Fan-out failure classification and counting."""

from __future__ import annotations

import asyncio
import logging

import pytest
from telegram.error import BadRequest, Forbidden, TimedOut

from tcbot.utils.dispatch import (
    count_transient_errors,
    fan_out,
    gather_bounded,
    is_benign_telegram_error,
    summarize_fanout,
)


def test_benign_patterns_recognized() -> None:
    assert is_benign_telegram_error(BadRequest("USER_NOT_PARTICIPANT")) is True
    assert is_benign_telegram_error(BadRequest("CHAT_NOT_FOUND")) is True
    assert is_benign_telegram_error(BadRequest("CHAT_ADMIN_REQUIRED")) is True


def test_human_readable_refusal_recognized() -> None:
    assert is_benign_telegram_error(BadRequest("User not participant")) is True


def test_unknown_and_non_request_errors_not_benign() -> None:
    assert is_benign_telegram_error(BadRequest("something else entirely")) is False
    assert is_benign_telegram_error(TimedOut("slow")) is False
    assert is_benign_telegram_error(Forbidden("denied")) is False
    assert is_benign_telegram_error(ValueError("x")) is False


def test_count_transient_errors_excludes_benign_refusals() -> None:
    results = [
        BadRequest("USER_NOT_PARTICIPANT"),
        1,
        BadRequest("other"),
        TimedOut("t"),
    ]
    assert count_transient_errors(results) == 2


def test_summarize_fanout_counts_a_benign_refusal_as_applied() -> None:
    """A group the user was never in counts as applied, not failed.

    There was nothing to enforce there, so the action landed as far as it
    could. Only a real failure counts against the action.
    """
    groups = [
        {"chat_id": -1, "title": "One"},
        {"chat_id": -2, "title": "Two"},
        {"chat_id": -3, "title": "Three"},
    ]
    results = [True, BadRequest("USER_NOT_PARTICIPANT"), TimedOut("slow")]

    outcome = summarize_fanout(groups, results, action="Ban", target_id=42)

    assert outcome.total == 3
    assert outcome.applied == 2
    assert outcome.failed == 1
    assert [grp["chat_id"] for grp, _exc in outcome.transient] == [-3]


def test_summarize_fanout_reports_no_failures_when_all_applied() -> None:
    groups = [{"chat_id": -1, "title": "One"}]
    outcome = summarize_fanout(groups, [True], action="Unban", target_id=42)

    assert outcome.applied == 1
    assert outcome.failed == 0
    assert outcome.transient == ()


def test_summarize_fanout_logs_the_failing_group(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The operator sees which group failed, not only how many."""
    groups = [{"chat_id": -2, "title": "Broken"}]

    with caplog.at_level(logging.WARNING, logger="tcbot.utils.dispatch"):
        summarize_fanout(groups, [TimedOut("slow")], action="Ban", target_id=42)

    assert any(
        "Ban enforcement failed for user=42" in record.getMessage()
        and "Broken" in record.getMessage()
        for record in caplog.records
    )


def test_fan_out_returns_regular_errors_as_data() -> None:
    async def _ok() -> str:
        return "ok"

    async def _fail() -> str:
        raise BadRequest("other")

    results = asyncio.run(fan_out([_ok(), _fail()]))
    assert results[0] == "ok"
    assert isinstance(results[1], BadRequest)


def test_fan_out_propagates_cancellation() -> None:
    async def _cancelled() -> str:
        raise asyncio.CancelledError

    async def _main() -> None:
        await fan_out([_cancelled()])

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(_main())


def test_gather_bounded_empty_input() -> None:
    assert asyncio.run(gather_bounded([])) == []


def test_gather_bounded_returns_errors_as_data_in_order() -> None:
    async def _ok(v: int) -> int:
        return v

    async def _fail() -> int:
        raise ValueError("boom")

    results = asyncio.run(gather_bounded([_ok(1), _fail(), _ok(3)]))
    assert results[0] == 1
    assert isinstance(results[1], ValueError)
    assert results[2] == 3


def test_gather_bounded_propagates_cancellation() -> None:
    async def _cancelled() -> int:
        raise asyncio.CancelledError

    async def _main() -> None:
        await gather_bounded([_cancelled()])

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(_main())


def test_gather_bounded_caps_concurrency() -> None:
    in_flight = 0
    peak = 0

    async def _work() -> int:
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        await asyncio.sleep(0.01)
        in_flight -= 1
        return 1

    async def _main() -> list[int | BaseException]:
        return await gather_bounded([_work() for _ in range(20)], max_concurrent=3)

    assert asyncio.run(_main()) == [1] * 20
    assert peak <= 3
