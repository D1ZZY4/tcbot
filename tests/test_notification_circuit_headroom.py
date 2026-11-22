# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Review-card claims stay within the circuit's remaining admission window."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from tcbot import notification_worker
from tcbot.database import notifications_db
from tcbot.utils import circuit_breaker as _cb


class _FakeBot:
    pass


def test_a_near_tripped_circuit_limits_the_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    claimed: list[int] = []

    async def _claim(limit: int, **_kwargs: Any) -> list[dict[str, Any]]:
        claimed.append(limit)
        return []

    monkeypatch.setattr(notifications_db, "claim_due_tasks", _claim)
    _cb.telegram.reset()
    _cb.telegram.record_failure()
    try:
        asyncio.run(notification_worker.run_once(_FakeBot()))  # type: ignore[arg-type]
    finally:
        _cb.telegram.reset()

    assert claimed
    assert claimed[0] <= _cb.telegram._failure_threshold - 1
    assert claimed[0] < notification_worker._MAX_TASKS_PER_TICK
