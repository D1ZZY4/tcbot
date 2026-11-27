# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Admission reserved before a claim cannot be lost to a circuit opening mid-claim."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from tcbot import database as db
from tcbot.modules.helper.pipelines import moderation_enforcement as enforcement
from tcbot.utils import circuit_breaker as _cb
from tcbot.utils.dispatch import count_transient_errors, summarize_fanout


class _Bot:
    def __init__(self) -> None:
        self.unbanned: list[tuple[int, int]] = []

    async def unban_chat_member(self, chat_id: int, user_id: int) -> None:
        self.unbanned.append((chat_id, user_id))


def test_a_circuit_opening_during_the_claim_still_delivers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The attempt was charged at claim time, so skipping it would waste it."""
    completed: list[dict[str, Any]] = []

    async def _noop(*_args: Any, **_kwargs: Any) -> None:
        return None

    async def _claim_runs(limit: int = 10) -> list[dict[str, object]]:
        return [{"id": 1, "action_id": 2, "operation": "revoke"}]

    async def _load(_run_id: int) -> dict[str, object]:
        return {
            "target_user_id": 9,
            "action_type": "ban",
            "action_status": "expired",
            "operation": "revoke",
        }

    async def _claim_targets(_run_id: int, limit: int = 100) -> list[dict[str, object]]:
        # * Another caller trips the breaker while this claim is in flight.
        for _ in range(_cb.telegram._failure_threshold):
            _cb.telegram.record_failure()
        return [{"id": 3, "chat_id": -100, "attempt_count": 0}]

    async def _complete(_target_id: int, **kwargs: Any) -> None:
        completed.append(kwargs)

    monkeypatch.setattr(db.enforcement_ledger, "requeue_stale_runs", _noop)
    monkeypatch.setattr(db.enforcement_ledger, "claim_runs", _claim_runs)
    monkeypatch.setattr(db.enforcement_ledger, "load_run_action", _load)
    monkeypatch.setattr(db.enforcement_ledger, "claim_targets", _claim_targets)
    monkeypatch.setattr(db.enforcement_ledger, "complete_target", _complete)
    monkeypatch.setattr(db.users_roles, "is_owner", _is_not_owner)
    monkeypatch.setattr(enforcement, "demote_before_enforcement", _no_demote)

    bot = _Bot()
    _cb.telegram.reset()
    try:
        asyncio.run(enforcement.run_once(bot))  # type: ignore[arg-type]
    finally:
        _cb.telegram.reset()

    assert bot.unbanned == [(-100, 9)]
    assert completed == [{"status": "succeeded", "outcome": "succeeded"}]


async def _is_not_owner(_user_id: int, *, fresh: bool = False) -> bool:
    return False


async def _no_demote(*_args: Any, **_kwargs: Any) -> str | None:
    return None


def test_circuit_skips_are_neither_applied_nor_failed_groups() -> None:
    skipped = [_cb.CircuitOpenError("skipped")]
    assert count_transient_errors(skipped) == 0

    outcome = summarize_fanout(
        [{"chat_id": -100, "title": "A"}],
        skipped,
        action="ban",
        target_id=9,
    )
    assert outcome.total == 1
    assert outcome.applied == 0
    assert outcome.failed == 1
    assert outcome.transient == ()
