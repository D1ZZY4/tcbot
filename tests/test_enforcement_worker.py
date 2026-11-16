# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Enforcement worker: queued expiry revokes reach Telegram."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from telegram.error import BadRequest

from tcbot import database as db
from tcbot import enforcement_worker
from tcbot.database import enforcement_db


class _FakeBot:
    def __init__(self) -> None:
        self.unbanned: list[tuple[int, int]] = []
        self.banned: list[tuple[int, int]] = []
        self.restricted: list[tuple[int, int, Any]] = []
        self.restrict_until: list[Any] = []

    async def ban_chat_member(self, chat_id: int, user_id: int) -> None:
        self.banned.append((chat_id, user_id))

    async def unban_chat_member(
        self, chat_id: int, user_id: int, *, only_if_banned: bool = False
    ) -> None:
        self.unbanned.append((chat_id, user_id))

    async def restrict_chat_member(
        self, chat_id: int, user_id: int, permissions: Any, **kwargs: Any
    ) -> None:
        self.restricted.append((chat_id, user_id, permissions))
        self.restrict_until.append(kwargs.get("until_date"))


def _wire(
    monkeypatch: pytest.MonkeyPatch,
    *,
    action_type: str = "ban",
    action_status: str = "expired",
    result: object = None,
) -> dict[str, Any]:
    record: dict[str, Any] = {"completed": []}

    async def _requeue(*args: Any, **kwargs: Any) -> None:
        return None

    async def _claim_runs(limit: int = 10) -> list[dict[str, object]]:
        return [{"id": 1, "action_id": 2, "operation": "revoke"}]

    async def _load(run_id: int) -> dict[str, object]:
        return {
            "target_user_id": 9,
            "action_type": action_type,
            "action_status": action_status,
            "operation": "revoke",
        }

    async def _targets(run_id: int, limit: int = 100) -> list[dict[str, object]]:
        return [{"id": 3, "chat_id": -100, "attempt_count": 0}]

    async def _complete(target_id: int, **kwargs: Any) -> None:
        record["completed"].append((target_id, kwargs))

    async def _fan_out(coros: Any) -> list[object]:
        for coro in coros:
            if result is None:
                await coro
            else:
                coro.close()
        return [result]

    monkeypatch.setattr(enforcement_db, "requeue_stale_runs", _requeue)
    monkeypatch.setattr(enforcement_db, "claim_runs", _claim_runs)
    monkeypatch.setattr(enforcement_db, "load_run_action", _load)
    monkeypatch.setattr(enforcement_db, "claim_targets", _targets)
    monkeypatch.setattr(enforcement_db, "complete_target", _complete)
    monkeypatch.setattr(enforcement_worker, "fan_out", _fan_out)
    return record


def test_an_expired_ban_is_lifted(monkeypatch: pytest.MonkeyPatch) -> None:
    record = _wire(monkeypatch)
    bot = _FakeBot()

    asyncio.run(enforcement_worker.run_once(bot))  # type: ignore[arg-type]

    assert bot.unbanned == [(-100, 9)]
    assert record["completed"] == [(3, {"status": "succeeded", "outcome": "succeeded"})]


def test_an_active_ban_apply_is_delivered(monkeypatch: pytest.MonkeyPatch) -> None:
    """An apply run bans the target in every claimed chat."""
    completed: list[tuple[int, dict[str, Any]]] = []

    async def _requeue(*args: Any, **kwargs: Any) -> None:
        return None

    async def _claim_runs(limit: int = 10) -> list[dict[str, object]]:
        return [{"id": 1, "action_id": 2, "operation": "apply"}]

    async def _load(run_id: int) -> dict[str, object]:
        return {
            "target_user_id": 9,
            "action_type": "ban",
            "action_status": "active",
            "operation": "apply",
            "expires_at": None,
        }

    async def _targets(run_id: int, limit: int = 100) -> list[dict[str, object]]:
        return [{"id": 3, "chat_id": -100, "attempt_count": 0}]

    async def _complete(target_id: int, **kwargs: Any) -> None:
        completed.append((target_id, kwargs))

    async def _fan_out(coros: Any) -> list[object]:
        for coro in coros:
            await coro
        return [None]

    monkeypatch.setattr(enforcement_db, "requeue_stale_runs", _requeue)
    monkeypatch.setattr(enforcement_db, "claim_runs", _claim_runs)
    monkeypatch.setattr(enforcement_db, "load_run_action", _load)
    monkeypatch.setattr(enforcement_db, "claim_targets", _targets)
    monkeypatch.setattr(enforcement_db, "complete_target", _complete)
    monkeypatch.setattr(enforcement_worker, "fan_out", _fan_out)
    bot = _FakeBot()

    asyncio.run(enforcement_worker.run_once(bot))  # type: ignore[arg-type]

    assert bot.banned == [(-100, 9)]
    assert completed == [(3, {"status": "succeeded", "outcome": "succeeded"})]


def test_an_active_mute_apply_keeps_its_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An apply run restricts the chat until the stored decision expiry."""
    deadline = datetime.now(UTC) + timedelta(hours=1)

    async def _requeue(*args: Any, **kwargs: Any) -> None:
        return None

    async def _claim_runs(limit: int = 10) -> list[dict[str, object]]:
        return [{"id": 1, "action_id": 2, "operation": "apply"}]

    async def _load(run_id: int) -> dict[str, object]:
        return {
            "target_user_id": 9,
            "action_type": "mute",
            "action_status": "active",
            "operation": "apply",
            "expires_at": deadline,
        }

    async def _targets(run_id: int, limit: int = 100) -> list[dict[str, object]]:
        return [{"id": 3, "chat_id": -100, "attempt_count": 0}]

    async def _complete(target_id: int, **kwargs: Any) -> None:
        return None

    async def _fan_out(coros: Any) -> list[object]:
        for coro in coros:
            await coro
        return [None]

    monkeypatch.setattr(enforcement_db, "requeue_stale_runs", _requeue)
    monkeypatch.setattr(enforcement_db, "claim_runs", _claim_runs)
    monkeypatch.setattr(enforcement_db, "load_run_action", _load)
    monkeypatch.setattr(enforcement_db, "claim_targets", _targets)
    monkeypatch.setattr(enforcement_db, "complete_target", _complete)
    monkeypatch.setattr(enforcement_worker, "fan_out", _fan_out)
    bot = _FakeBot()

    asyncio.run(enforcement_worker.run_once(bot))  # type: ignore[arg-type]

    assert len(bot.restricted) == 1
    assert bot.restricted[0][2].can_send_messages is False
    assert bot.restrict_until == [deadline]


def test_an_apply_that_outlived_its_deadline_is_cancelled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A delayed apply must not restrict a target past the stored deadline."""
    cancelled: list[int] = []
    claimed: list[int] = []
    deadline = datetime.now(UTC) - timedelta(minutes=1)

    async def _requeue(*args: Any, **kwargs: Any) -> None:
        return None

    async def _claim_runs(limit: int = 10) -> list[dict[str, object]]:
        return [{"id": 1, "action_id": 2, "operation": "apply"}]

    async def _load(run_id: int) -> dict[str, object]:
        return {
            "target_user_id": 9,
            "action_type": "mute",
            "action_status": "active",
            "operation": "apply",
            "expires_at": deadline,
        }

    async def _targets(run_id: int, limit: int = 100) -> list[dict[str, object]]:
        claimed.append(run_id)
        return [{"id": 3, "chat_id": -100, "attempt_count": 0}]

    async def _cancel(run_id: int, **kwargs: Any) -> None:
        cancelled.append(run_id)

    monkeypatch.setattr(enforcement_db, "requeue_stale_runs", _requeue)
    monkeypatch.setattr(enforcement_db, "claim_runs", _claim_runs)
    monkeypatch.setattr(enforcement_db, "load_run_action", _load)
    monkeypatch.setattr(enforcement_db, "claim_targets", _targets)
    monkeypatch.setattr(enforcement_db, "cancel_run", _cancel)
    bot = _FakeBot()

    asyncio.run(enforcement_worker.run_once(bot))  # type: ignore[arg-type]

    assert cancelled == [1]
    assert claimed == []
    assert bot.restricted == []


def test_an_expired_mute_is_restored(monkeypatch: pytest.MonkeyPatch) -> None:
    _wire(monkeypatch, action_type="mute")
    bot = _FakeBot()

    asyncio.run(enforcement_worker.run_once(bot))  # type: ignore[arg-type]

    assert len(bot.restricted) == 1
    chat_id, user_id, permissions = bot.restricted[0]
    assert (chat_id, user_id) == (-100, 9)
    assert permissions.can_send_messages is True


def test_a_benign_telegram_refusal_is_skipped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = _wire(monkeypatch, result=BadRequest("USER_NOT_PARTICIPANT"))

    asyncio.run(enforcement_worker.run_once(_FakeBot()))  # type: ignore[arg-type]

    assert record["completed"][0][1]["status"] == "skipped"


def test_a_missing_admin_right_is_a_terminal_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A demoted bot did not apply the action and retrying cannot fix it."""
    record = _wire(monkeypatch, result=BadRequest("CHAT_ADMIN_REQUIRED"))

    asyncio.run(enforcement_worker.run_once(_FakeBot()))  # type: ignore[arg-type]

    outcome = record["completed"][0][1]
    assert outcome["status"] == "failed"
    assert outcome["outcome"] == "failed"
    assert outcome["error_kind"] == "permanent"
    assert outcome.get("retry_after") is None


def test_a_transient_failure_gets_a_bounded_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = _wire(monkeypatch, result=RuntimeError("network down"))

    asyncio.run(enforcement_worker.run_once(_FakeBot()))  # type: ignore[arg-type]

    status = record["completed"][0][1]
    # * A retry is a failed attempt with a due deadline: the target trigger
    # * refuses in_progress -> pending, which would strand the target.
    assert status["status"] == "failed"
    assert status["outcome"] == "failed"
    assert status["retry_after"] is not None


def test_a_revoke_with_a_newer_active_decision_is_cancelled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A retried revoke must not lift a restriction that was reinstated.

    The ban was revoked, the unban run was queued, and a new ban landed
    before the worker retried the old delivery. Applying the stale revoke
    would unban the target while the new decision is active.
    """
    cancelled: list[int] = []

    async def _requeue(*args: Any, **kwargs: Any) -> None:
        return None

    async def _claim_runs(limit: int = 10) -> list[dict[str, object]]:
        return [{"id": 1, "action_id": 2, "operation": "revoke"}]

    async def _load(run_id: int) -> dict[str, object]:
        return {
            "target_user_id": 9,
            "action_type": "ban",
            "action_status": "revoked",
            "operation": "revoke",
            "newer_active": True,
        }

    async def _cancel(run_id: int, **kwargs: Any) -> None:
        cancelled.append(run_id)

    monkeypatch.setattr(enforcement_db, "requeue_stale_runs", _requeue)
    monkeypatch.setattr(enforcement_db, "claim_runs", _claim_runs)
    monkeypatch.setattr(enforcement_db, "load_run_action", _load)
    monkeypatch.setattr(enforcement_db, "cancel_run", _cancel)
    bot = _FakeBot()

    asyncio.run(enforcement_worker.run_once(bot))  # type: ignore[arg-type]

    assert cancelled == [1]
    assert bot.unbanned == []


def test_a_kick_repair_is_cancelled_when_a_ban_is_active(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Repairing a stranded kick must not lift a federation ban."""
    cancelled: list[int] = []

    async def _requeue(*args: Any, **kwargs: Any) -> None:
        return None

    async def _claim_runs(limit: int = 10) -> list[dict[str, object]]:
        return [{"id": 5, "action_id": 6, "operation": "reconcile"}]

    async def _load(run_id: int) -> dict[str, object]:
        return {
            "target_user_id": 9,
            "action_type": "kick",
            "action_status": "completed",
            "operation": "reconcile",
            "active_ban": True,
        }

    async def _cancel(run_id: int, **kwargs: Any) -> None:
        cancelled.append(run_id)

    monkeypatch.setattr(enforcement_db, "requeue_stale_runs", _requeue)
    monkeypatch.setattr(enforcement_db, "claim_runs", _claim_runs)
    monkeypatch.setattr(enforcement_db, "load_run_action", _load)
    monkeypatch.setattr(enforcement_db, "cancel_run", _cancel)
    bot = _FakeBot()

    asyncio.run(enforcement_worker.run_once(bot))  # type: ignore[arg-type]

    assert cancelled == [5]
    assert bot.unbanned == []


def test_the_requeue_uses_legal_target_transitions() -> None:
    """Stale targets are released as failed, never back to pending.

    The target trigger accepts in_progress -> succeeded|skipped|failed
    only. Writing pending aborts the whole transaction and leaves the
    target and its run stuck, so the SQL is pinned here.
    """
    assert "status = 'failed'" in enforcement_db._REQUEUE_TARGETS.text
    assert "status = 'pending'" not in enforcement_db._REQUEUE_TARGETS.text


def test_a_due_retry_requeues_its_run() -> None:
    """A run that closed on a retryable failure must reopen when due.

    The target can only be claimed through a running run, so the run
    statement has to pick up failed targets whose deadline arrived.
    """
    sql = enforcement_db._REQUEUE_RUNS.text
    assert "t.status = 'failed'" in sql
    assert "t.next_retry_at <= now()" in sql
    assert "cc.is_active" in sql


def test_a_delivery_outcome_keeps_pending_groups_out_of_applied() -> None:
    """The target rows decide the result, not the failure subtraction.

    A group that was requested but has no target row (it disconnected
    during the proof window) is still part of the total and counts as
    pending, so the summary cannot claim a complete delivery.
    """
    report = {
        "status": "running",
        "targets": [
            {"status": "succeeded"},
            {"status": "failed"},
            {"status": "in_progress"},
        ],
    }

    outcome = enforcement_db.delivery_outcome(report, 9)

    assert (outcome.total, outcome.applied, outcome.failed, outcome.pending) == (
        9,
        1,
        1,
        7,
    )
    assert enforcement_db.report_settled(report) is False


def test_an_unreadable_report_is_not_a_successful_delivery() -> None:
    outcome = enforcement_db.delivery_outcome(None, 4)

    assert (outcome.total, outcome.applied, outcome.failed, outcome.pending) == (
        4,
        0,
        0,
        4,
    )


def test_a_kick_repair_run_lifts_the_second_step(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A reconcile run for a kick unbans the chat the kick could not release."""
    completed: list[tuple[int, dict[str, Any]]] = []
    restored: list[int] = []

    async def _requeue(*args: Any, **kwargs: Any) -> None:
        return None

    async def _claim_runs(limit: int = 10) -> list[dict[str, object]]:
        return [{"id": 5, "action_id": 6, "operation": "reconcile"}]

    async def _load(run_id: int) -> dict[str, object]:
        return {
            "action_id": 6,
            "target_user_id": 9,
            "action_type": "kick",
            "action_status": "failed",
            "operation": "reconcile",
        }

    async def _targets(run_id: int, limit: int = 100) -> list[dict[str, object]]:
        return [{"id": 7, "chat_id": -100, "attempt_count": 0}]

    async def _complete(target_id: int, **kwargs: Any) -> None:
        completed.append((target_id, kwargs))

    async def _restore(action_id: int) -> bool:
        restored.append(action_id)
        return True

    async def _fan_out(coros: Any) -> list[object]:
        for coro in coros:
            await coro
        return [None]

    monkeypatch.setattr(enforcement_db, "requeue_stale_runs", _requeue)
    monkeypatch.setattr(enforcement_db, "claim_runs", _claim_runs)
    monkeypatch.setattr(enforcement_db, "load_run_action", _load)
    monkeypatch.setattr(enforcement_db, "claim_targets", _targets)
    monkeypatch.setattr(enforcement_db, "complete_target", _complete)
    monkeypatch.setattr(db.kicks_db, "mark_kick_completed", _restore)
    monkeypatch.setattr(enforcement_worker, "fan_out", _fan_out)
    bot = _FakeBot()

    asyncio.run(enforcement_worker.run_once(bot))  # type: ignore[arg-type]

    assert bot.unbanned == [(-100, 9)]
    assert completed == [(7, {"status": "succeeded", "outcome": "succeeded"})]
    assert restored == [6]


def test_a_reconcile_run_for_another_action_is_cancelled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cancelled: list[int] = []

    async def _requeue(*args: Any, **kwargs: Any) -> None:
        return None

    async def _claim_runs(limit: int = 10) -> list[dict[str, object]]:
        return [{"id": 5, "action_id": 6, "operation": "reconcile"}]

    async def _load(run_id: int) -> dict[str, object]:
        return {
            "target_user_id": 9,
            "action_type": "ban",
            "action_status": "active",
            "operation": "reconcile",
        }

    monkeypatch.setattr(enforcement_db, "requeue_stale_runs", _requeue)
    monkeypatch.setattr(enforcement_db, "claim_runs", _claim_runs)
    monkeypatch.setattr(enforcement_db, "load_run_action", _load)
    monkeypatch.setattr(
        enforcement_db,
        "cancel_run",
        lambda run_id, **kwargs: _record(cancelled, run_id),
    )

    asyncio.run(enforcement_worker.run_once(_FakeBot()))  # type: ignore[arg-type]

    assert cancelled == [5]


def test_deliver_queued_run_reports_a_lost_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(enforcement_db, "claim_run", lambda run_id: _async_value(None))

    delivered = asyncio.run(
        enforcement_worker.deliver_queued_run(_FakeBot(), 5)  # type: ignore[arg-type]
    )

    assert delivered is False


def test_a_run_for_an_active_action_is_cancelled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cancelled: list[int] = []
    monkeypatch.setattr(
        enforcement_db,
        "claim_runs",
        lambda limit=10: _async_value([{"id": 1, "action_id": 2}]),
    )
    monkeypatch.setattr(
        enforcement_db,
        "requeue_stale_runs",
        lambda *args, **kwargs: _async_none(),
    )
    monkeypatch.setattr(
        enforcement_db,
        "load_run_action",
        lambda run_id: _async_value(
            {
                "target_user_id": 9,
                "action_type": "ban",
                "action_status": "active",
            }
        ),
    )
    monkeypatch.setattr(
        enforcement_db,
        "cancel_run",
        lambda run_id, **kwargs: _record(cancelled, run_id),
    )
    monkeypatch.setattr(
        enforcement_db,
        "claim_targets",
        lambda *args, **kwargs: _async_value([]),
    )

    asyncio.run(enforcement_worker.run_once(_FakeBot()))  # type: ignore[arg-type]

    assert cancelled == [1]


def test_one_failed_run_does_not_stop_the_next(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A broken run must not leave the rest of the claimed batch unprocessed."""
    loaded: list[int] = []

    async def _requeue(*args: Any, **kwargs: Any) -> None:
        return None

    async def _claim_runs(limit: int = 10) -> list[dict[str, object]]:
        return [
            {"id": 1, "action_id": 2, "operation": "revoke"},
            {"id": 2, "action_id": 3, "operation": "revoke"},
        ]

    async def _load(run_id: int) -> dict[str, object]:
        loaded.append(run_id)
        if run_id == 1:
            raise RuntimeError("the first run is broken")
        return {
            "target_user_id": 9,
            "action_type": "ban",
            "action_status": "expired",
            "operation": "revoke",
        }

    async def _targets(run_id: int, limit: int = 100) -> list[dict[str, object]]:
        return [{"id": 3, "chat_id": -100, "attempt_count": 0}]

    completed: list[int] = []

    async def _complete(target_id: int, **kwargs: Any) -> None:
        completed.append(target_id)

    async def _fan_out(coros: Any) -> list[object]:
        for coro in coros:
            await coro
        return [None]

    monkeypatch.setattr(enforcement_db, "requeue_stale_runs", _requeue)
    monkeypatch.setattr(enforcement_db, "claim_runs", _claim_runs)
    monkeypatch.setattr(enforcement_db, "load_run_action", _load)
    monkeypatch.setattr(enforcement_db, "claim_targets", _targets)
    monkeypatch.setattr(enforcement_db, "complete_target", _complete)
    monkeypatch.setattr(enforcement_worker, "fan_out", _fan_out)

    asyncio.run(enforcement_worker.run_once(_FakeBot()))  # type: ignore[arg-type]

    assert loaded == [1, 2]
    assert completed == [3]


async def _async_value(value: Any) -> Any:
    return value


async def _async_none() -> None:
    return None


async def _record(target: list[int], value: int) -> None:
    target.append(value)
