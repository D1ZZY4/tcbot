# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Enforcement claims stay within the circuit's remaining admission window."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from tcbot.database import enforcement_ledger
from tcbot.modules.helper.pipelines import moderation_enforcement
from tcbot.utils import circuit_breaker as _cb


class _FakeBot:
    async def unban_chat_member(self, *_args: Any, **_kwargs: Any) -> bool:
        return True


def test_the_breaker_reports_its_closed_admission_headroom() -> None:
    _cb.telegram.reset()
    try:
        threshold = _cb.telegram._failure_threshold
        assert _cb.telegram.admission_headroom == threshold
        _cb.telegram.record_failure()
        assert _cb.telegram.admission_headroom == threshold - 1
        for _ in range(threshold):
            _cb.telegram.record_failure()
        assert _cb.telegram.state is _cb.CircuitState.OPEN
        assert _cb.telegram.admission_headroom == 0
    finally:
        _cb.telegram.reset()


def test_a_mid_tick_circuit_open_returns_claimed_runs_to_the_queue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A run claimed just before the circuit opens must not wait 30 minutes."""

    async def _requeue(*_args: Any, **_kwargs: Any) -> None:
        return None

    async def _claim_runs(limit: int = 10) -> list[dict[str, object]]:
        return [
            {"id": 1, "action_id": 2, "operation": "revoke"},
            {"id": 2, "action_id": 3, "operation": "revoke"},
        ]

    processed: list[int] = []

    async def _process(bot: Any, run: dict[str, object], **_kwargs: Any) -> None:
        processed.append(int(str(run["id"])))
        _cb.telegram._state = _cb.CircuitState.OPEN

    deferred: list[list[int]] = []

    async def _defer(run_ids: Any) -> int:
        deferred.append(list(run_ids))
        return len(run_ids)

    monkeypatch.setattr(enforcement_ledger, "requeue_stale_runs", _requeue)
    monkeypatch.setattr(enforcement_ledger, "claim_runs", _claim_runs)
    monkeypatch.setattr(enforcement_ledger, "defer_runs", _defer)
    monkeypatch.setattr(moderation_enforcement, "_process_run", _process)

    _cb.telegram.reset()
    try:
        asyncio.run(
            moderation_enforcement.run_once(_FakeBot())  # type: ignore[arg-type]
        )
    finally:
        _cb.telegram.reset()

    assert processed == [1, 2]
    assert deferred == [[1, 2]]


def test_no_delivery_chunk_exceeds_the_headroom(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A near-tripped circuit never claims more targets than it can deliver."""

    async def _requeue(*_args: Any, **_kwargs: Any) -> None:
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

    claims: list[int] = []

    async def _targets(run_id: int, limit: int = 100) -> list[dict[str, object]]:
        claims.append(limit)
        if len(claims) == 1:
            return [
                {"id": 3, "chat_id": -100, "attempt_count": 0},
                {"id": 4, "chat_id": -101, "attempt_count": 0},
            ]
        return []

    async def _complete(*_args: Any, **_kwargs: Any) -> None:
        return None

    async def _fan_out(coros: Any) -> list[object]:
        for coro in coros:
            await coro
        return [None] * len(coros)

    monkeypatch.setattr(enforcement_ledger, "requeue_stale_runs", _requeue)
    monkeypatch.setattr(enforcement_ledger, "claim_runs", _claim_runs)
    monkeypatch.setattr(enforcement_ledger, "load_run_action", _load)
    monkeypatch.setattr(enforcement_ledger, "claim_targets", _targets)
    monkeypatch.setattr(enforcement_ledger, "complete_target", _complete)
    monkeypatch.setattr(enforcement_ledger, "complete_empty_run", _complete)
    monkeypatch.setattr(moderation_enforcement, "fan_out", _fan_out)

    _cb.telegram.reset()
    _cb.telegram.record_failure()
    try:
        asyncio.run(
            moderation_enforcement.run_once(_FakeBot())  # type: ignore[arg-type]
        )
    finally:
        _cb.telegram.reset()

    assert claims
    assert max(claims) <= _cb.telegram._failure_threshold - 1
