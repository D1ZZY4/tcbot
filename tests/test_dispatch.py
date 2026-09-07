# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Fan-out failure classification and counting."""

from __future__ import annotations

import asyncio

import pytest
from telegram.error import BadRequest, Forbidden, TimedOut

from tcbot.utils.dispatch import (
    count_errors,
    count_transient_errors,
    fan_out,
    is_benign_telegram_error,
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


def test_counters_split_benign_from_transient() -> None:
    results = [
        BadRequest("USER_NOT_PARTICIPANT"),
        1,
        BadRequest("other"),
        TimedOut("t"),
    ]
    assert count_errors(results) == 3
    assert count_transient_errors(results) == 2


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
