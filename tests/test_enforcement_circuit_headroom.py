# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Enforcement claims stay within the circuit's remaining admission window."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from tcbot import enforcement_worker
from tcbot.database import enforcement_db
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

    monkeypatch.setattr(enforcement_db, "requeue_stale_runs", _requeue)
    monkeypatch.setattr(enforcement_db, "claim_runs", _claim_runs)
    monkeypatch.setattr(enforcement_db, "load_run_action", _load)
    monkeypatch.setattr(enforcement_db, "claim_targets", _targets)
    monkeypatch.setattr(enforcement_db, "complete_target", _complete)
    monkeypatch.setattr(enforcement_db, "complete_empty_run", _complete)
    monkeypatch.setattr(enforcement_worker, "fan_out", _fan_out)

    _cb.telegram.reset()
    _cb.telegram.record_failure()
    try:
        asyncio.run(
            enforcement_worker.run_once(_FakeBot())  # type: ignore[arg-type]
        )
    finally:
        _cb.telegram.reset()

    assert claims
    assert max(claims) <= _cb.telegram._failure_threshold - 1
