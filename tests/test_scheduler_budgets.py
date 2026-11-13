# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Scheduled sweeps must honour the deadline they report.

The expiry sweep moves the decisions and the role assignments that ran
out. The work happens over the whole history, so the sweep carries a
generous budget. The budget has to reach the statement that does the
work: a shorter timeout underneath would abort the sweep while the log
line named the longer one.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from tcbot.database import scheduler


def test_the_expiry_sweep_carries_its_own_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The expiry transaction must run with the budget the sweep reports."""
    seen: dict[str, Any] = {}

    async def _fake_run_transaction(op: Any, **kwargs: Any) -> dict[str, Any]:
        seen["timeout"] = kwargs.get("timeout")
        return {}

    monkeypatch.setattr(scheduler, "run_transaction", _fake_run_transaction)

    asyncio.run(scheduler.expire_due_decisions())

    assert seen["timeout"] == scheduler._EXPIRE_OP_TIMEOUT_S


def test_a_failed_sweep_does_not_report_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A rolled-back sweep must raise, not look like a finished one."""

    async def _fake_run_transaction(op: Any, **kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("db blip")

    monkeypatch.setattr(scheduler, "run_transaction", _fake_run_transaction)

    with pytest.raises(RuntimeError, match="rolled back"):
        asyncio.run(scheduler.expire_due_decisions())
