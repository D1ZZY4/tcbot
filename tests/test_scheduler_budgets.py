# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Scheduled sweeps must honour the deadline they report.

The warn expiry prunes both warning tables in one transaction. A bulk
delete over a large history can run long, so the sweep carries a
generous budget. The budget has to reach the statement that runs the
delete: a shorter timeout underneath would abort the prune while the
log line named the longer one.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from tcbot.database import scheduler


def test_the_warn_expiry_carries_its_own_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The expiry transaction must run with the budget the sweep reports."""
    seen: dict[str, Any] = {}

    async def _fake_run_transaction(op: Any, **kwargs: Any) -> tuple[int, int]:
        seen["timeout"] = kwargs.get("timeout")
        return (0, 0)

    monkeypatch.setattr(scheduler, "run_transaction", _fake_run_transaction)

    asyncio.run(scheduler.expire_old_warns(7))

    assert seen["timeout"] == scheduler._EXPIRE_OP_TIMEOUT_S


def test_a_disabled_expiry_touches_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A non-positive expiry window is a no-op, not a full prune."""
    called = False

    async def _fake_run_transaction(op: Any, **kwargs: Any) -> tuple[int, int]:
        nonlocal called
        called = True
        return (0, 0)

    monkeypatch.setattr(scheduler, "run_transaction", _fake_run_transaction)

    asyncio.run(scheduler.expire_old_warns(0))

    assert called is False
