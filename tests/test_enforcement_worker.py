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
    assert status["status"] == "pending"
    assert status["outcome"] == "failed"
    assert status["retry_after"] is not None


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


async def _async_value(value: Any) -> Any:
    return value


async def _async_none() -> None:
    return None


async def _record(target: list[int], value: int) -> None:
    target.append(value)
