# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Fan-out failure classification and counting."""

from __future__ import annotations

import asyncio
import inspect
import logging

import pytest
from pyrogram.errors import (
    OffsetPeerIdInvalid,
    PeerIdInvalid,
    ReplyMessageIdInvalid,
    UserIsBot,
)
from pyrogram.raw.types import RpcError

from tcbot.modules.helper.messages.replies import applied_summary
from tcbot.modules.helper.pipelines.errors.exceptions import (
    BadRequest,
    Forbidden,
    Timedout,
)
from tcbot.utils import circuit_breaker as _cb
from tcbot.utils.dispatch import (
    count_transient_errors,
    fan_out,
    gather_bounded,
    is_benign_telegram_error,
    is_edit_target_gone_error,
    is_permanent_telegram_error,
    summarize_fanout,
)


def test_benign_patterns_recognized() -> None:
    assert is_benign_telegram_error(BadRequest("USER_NOT_PARTICIPANT")) is True
    assert is_benign_telegram_error(BadRequest("CHAT_NOT_FOUND")) is True


def test_missing_admin_rights_is_not_benign() -> None:
    """A demoted bot did not enforce anything, so it is not a no-op."""
    assert is_benign_telegram_error(BadRequest("CHAT_ADMIN_REQUIRED")) is False
    assert is_permanent_telegram_error(BadRequest("CHAT_ADMIN_REQUIRED")) is True


def test_a_lost_membership_is_permanent() -> None:
    assert is_permanent_telegram_error(Forbidden("Bot was kicked from the group chat"))
    assert is_permanent_telegram_error(BadRequest("CHAT_WRITE_FORBIDDEN"))
    assert is_permanent_telegram_error(TimeoutError("slow")) is False
    assert is_permanent_telegram_error(BadRequest("USER_NOT_PARTICIPANT")) is False


def test_applied_summary_does_not_count_a_pending_group_as_done() -> None:
    """A run that has not answered yet is reported as progress, not success."""
    line = applied_summary(
        "en-US",
        "banning.applied",
        total=2,
        failed=0,
        pending=1,
        transient=(),
    )

    assert "1/2" in line
    assert "awaiting delivery" in line


def test_real_rpc_names_do_not_collide_with_benign_markers() -> None:
    """Normalized substrings must not turn a bad peer into a no-op."""
    assert is_benign_telegram_error(OffsetPeerIdInvalid()) is False
    assert is_benign_telegram_error(UserIsBot()) is True
    assert is_edit_target_gone_error(OffsetPeerIdInvalid()) is False
    assert is_edit_target_gone_error(ReplyMessageIdInvalid()) is False


def test_a_local_peer_resolution_failure_is_not_a_no_op() -> None:
    """A missing access hash means Telegram never received the action."""
    local = PeerIdInvalid()
    assert local.raw is None
    assert is_benign_telegram_error(local) is False


def test_a_server_peer_refusal_is_still_benign() -> None:
    """The same RPC code from Telegram means the target is genuinely absent."""
    server = PeerIdInvalid(
        raw_error=RpcError(error_code=400, error_message="PEER_ID_INVALID")
    )
    assert server.raw is not None
    assert is_benign_telegram_error(server) is True


def test_human_readable_refusal_recognized() -> None:
    assert is_benign_telegram_error(BadRequest("User not participant")) is True


def test_unknown_and_non_request_errors_not_benign() -> None:
    assert is_benign_telegram_error(BadRequest("something else entirely")) is False
    assert is_benign_telegram_error(TimeoutError("slow")) is False
    assert is_benign_telegram_error(Forbidden("denied")) is False
    assert is_benign_telegram_error(ValueError("x")) is False


def test_count_transient_errors_excludes_benign_refusals() -> None:
    results = [
        BadRequest("USER_NOT_PARTICIPANT"),
        1,
        BadRequest("other"),
        TimeoutError("t"),
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
    results = [True, BadRequest("USER_NOT_PARTICIPANT"), TimeoutError("slow")]

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
        summarize_fanout(groups, [TimeoutError("slow")], action="Ban", target_id=42)

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


def test_fan_out_counts_a_wrapper_timeout_against_the_circuit() -> None:
    """A caller-side timeout is a transport stall, not a service response."""

    async def _timeout() -> str:
        raise TimeoutError("delivery exceeded its bound")

    _cb.telegram.reset()
    before = _cb.telegram._failure_count
    try:
        results = asyncio.run(fan_out([_timeout()]))
        assert isinstance(results[0], TimeoutError)
        assert _cb.telegram._failure_count == before + 1
    finally:
        _cb.telegram.reset()


def test_fan_out_counts_a_client_rpc_timeout_against_the_circuit() -> None:
    """Kurigram deadlines are transport stalls, not service answers.

    The client raises Timedout as an RPCError rather than a builtin
    TimeoutError. Treating it as an answer would close a HALF_OPEN probe and
    admit a fresh flood while Telegram is still stalling.
    """

    async def _timeout() -> str:
        raise Timedout("telemetry.timeout")

    _cb.telegram.reset()
    _cb.telegram._state = _cb.CircuitState.HALF_OPEN
    assert _cb.telegram.try_acquire() is True
    try:
        results = asyncio.run(fan_out([_timeout()], probe_reserved=True))
        assert isinstance(results[0], Timedout)
        assert _cb.telegram.state is _cb.CircuitState.OPEN
        assert _cb.telegram._failure_count == 1
    finally:
        _cb.telegram.reset()


def test_fan_out_counts_a_network_error_but_not_a_service_refusal() -> None:
    """Only a transport failure counts against the breaker; a 403 does not."""

    async def _network() -> str:
        raise OSError("connection reset")

    async def _forbidden() -> str:
        raise Forbidden("denied")

    _cb.telegram.reset()
    before = _cb.telegram._failure_count
    try:
        results = asyncio.run(fan_out([_network(), _forbidden()]))
        assert isinstance(results[0], OSError)
        assert isinstance(results[1], Forbidden)
        assert _cb.telegram._failure_count == before + 1
        assert _cb.telegram.state is _cb.CircuitState.CLOSED
    finally:
        _cb.telegram.reset()


def test_a_reserved_probe_lets_its_call_through_and_blocks_others() -> None:
    """A reserved HALF_OPEN probe must not be rejected by its own fan-out."""

    async def _work() -> str:
        return "ok"

    async def _other() -> str:
        raise AssertionError("a second probe must not run")

    _cb.telegram.reset()
    _cb.telegram._state = _cb.CircuitState.HALF_OPEN
    try:
        assert _cb.telegram.try_acquire() is True
        blocked = asyncio.run(fan_out([_other()]))
        assert isinstance(blocked[0], _cb.CircuitOpenError)
        results = asyncio.run(fan_out([_work()], probe_reserved=True))
        assert results == ["ok"]
        assert _cb.telegram.state is _cb.CircuitState.CLOSED
    finally:
        _cb.telegram.reset()


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


def test_gather_bounded_closes_coroutines_that_never_started() -> None:
    """A cancelled burst must not leak the coroutines still waiting for a slot.

    The global cap admits one slot at a time, so the coroutines behind it
    were never awaited. Leaving them open holds whatever they captured and
    prints "coroutine was never awaited" at collection time.
    """

    async def _slow() -> int:
        await asyncio.sleep(5)
        return 1

    coros = [_slow(), _slow(), _slow()]

    async def _main() -> None:
        task = asyncio.create_task(gather_bounded(coros, max_concurrent=1))
        await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(_main())

    assert [inspect.getcoroutinestate(coro) for coro in coros] == [
        inspect.CORO_CLOSED,
        inspect.CORO_CLOSED,
        inspect.CORO_CLOSED,
    ]


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


def test_fan_out_caps_concurrency_and_keeps_order() -> None:
    in_flight = 0
    peak = 0

    async def _work(index: int) -> int:
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        await asyncio.sleep(0.01)
        in_flight -= 1
        return index

    async def _main() -> list[int | BaseException]:
        return await fan_out([_work(i) for i in range(20)], max_concurrent=3)

    assert asyncio.run(_main()) == list(range(20))
    assert peak <= 3
