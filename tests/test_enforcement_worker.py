# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Enforcement worker: queued expiry revokes reach Telegram."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from telegram.error import BadRequest

from tcbot import enforcement_worker
from tcbot.database import enforcement_db


class _FakeBot:
    def __init__(self) -> None:
        self.unbanned: list[tuple[int, int]] = []
        self.restricted: list[tuple[int, int, Any]] = []

    async def unban_chat_member(
        self, chat_id: int, user_id: int, *, only_if_banned: bool = False
    ) -> None:
        self.unbanned.append((chat_id, user_id))

    async def restrict_chat_member(
        self, chat_id: int, user_id: int, permissions: Any
    ) -> None:
        self.restricted.append((chat_id, user_id, permissions))


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
