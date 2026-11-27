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
from tcbot.database.scheduler import jobs as scheduler_jobs


def test_the_expiry_sweep_carries_its_own_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The expiry transaction must run with the budget the sweep reports."""
    seen: dict[str, Any] = {}

    async def _fake_run_transaction(op: Any, **kwargs: Any) -> dict[str, Any]:
        seen["timeout"] = kwargs.get("timeout")
        return {}

    monkeypatch.setattr(scheduler_jobs, "run_transaction", _fake_run_transaction)

    asyncio.run(scheduler.expire_due_decisions())

    assert seen["timeout"] == scheduler._EXPIRE_OP_TIMEOUT_S


def test_a_failed_sweep_does_not_report_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A rolled-back sweep must raise, not look like a finished one."""

    async def _fake_run_transaction(op: Any, **kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("db blip")

    monkeypatch.setattr(scheduler_jobs, "run_transaction", _fake_run_transaction)

    with pytest.raises(RuntimeError, match="rolled back"):
        asyncio.run(scheduler.expire_due_decisions())


def test_expiry_invalidates_the_cached_roles_of_expired_users(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A role that expires on schedule must leave the cache immediately.

    The sweep flips the rows in the database, but non-fresh readers get
    their role from the two-level cache. Without an invalidation after the
    commit, those readers keep serving the expired role for the whole TTL.
    """

    class _ScalarResult:
        def __init__(self, value: Any) -> None:
            self._value = value

        def scalar(self) -> Any:
            return self._value

    class _RowsResult:
        def __init__(self, rows: list[tuple[int, ...]]) -> None:
            self._rows = rows

        def __iter__(self) -> Any:
            return iter(self._rows)

    class _Session:
        async def scalar(self, statement: Any, params: Any = None) -> bool:
            _ = (statement, params)
            return True

        async def execute(self, statement: Any) -> Any:
            sql = str(statement)
            if "expire_due_moderation_actions" in sql:
                return _ScalarResult({"expired": 1})
            if "SELECT DISTINCT user_id" in sql:
                return _RowsResult([(42,), (43,)])
            if "expire_due_role_assignments_and_audit" in sql:
                return _ScalarResult({"expired_role_assignments": 2})
            raise AssertionError(f"unexpected statement: {sql}")

    async def _fake_run_transaction(op: Any, **kwargs: Any) -> Any:
        _ = kwargs
        return await op(_Session())

    invalidated: list[int] = []
    monkeypatch.setattr(scheduler_jobs, "run_transaction", _fake_run_transaction)
    monkeypatch.setattr(
        type(scheduler_jobs.effective_role_cache),
        "invalidate",
        lambda _self, key: invalidated.append(key),
    )

    asyncio.run(scheduler.expire_due_decisions())

    assert invalidated == [42, 43]


def test_the_retention_sweep_runs_the_registry_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The telemetry window must be applied through the job registry."""
    seen: dict[str, Any] = {}

    class _Session:
        async def scalar(self, statement: Any, params: Any = None) -> dict[str, int]:
            seen["sql"] = str(statement)
            seen["params"] = params
            return {"affected": 4}

    async def _fake_run_transaction(op: Any, **kwargs: Any) -> Any:
        return await op(_Session())

    monkeypatch.setattr(scheduler_jobs, "run_transaction", _fake_run_transaction)

    asyncio.run(scheduler.sweep_retention())

    assert "run_scheduled_job" in seen["sql"]
    assert "retention.sweep" in seen["sql"]
    params = seen["params"]
    assert set(params) == {"run_key"}
    assert params["run_key"].startswith("retention.sweep:")


def test_a_failed_retention_sweep_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A retention failure must reach the scheduler log, not look empty."""

    async def _fake_run_transaction(op: Any, **kwargs: Any) -> Any:
        raise RuntimeError("db blip")

    monkeypatch.setattr(scheduler_jobs, "run_transaction", _fake_run_transaction)

    with pytest.raises(RuntimeError, match="db blip"):
        asyncio.run(scheduler.sweep_retention())


def test_a_retention_job_failure_is_committed_before_the_caller_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The registry keeps the failed run instead of rolling it back."""

    class _Session:
        async def scalar(self, statement: Any, params: Any = None) -> dict[str, Any]:
            _ = (statement, params)
            return {"status": "failed", "error": "policy blocked", "affected": 0}

    async def _fake_run_transaction(op: Any, **kwargs: Any) -> Any:
        return await op(_Session())

    monkeypatch.setattr(scheduler_jobs, "run_transaction", _fake_run_transaction)

    with pytest.raises(RuntimeError, match="policy blocked"):
        asyncio.run(scheduler.sweep_retention())


def test_the_erasure_sweep_invalidates_the_processed_accounts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An erased profile must leave both cache layers before the tick ends.

    The erasure and the invalidation are separate steps: a queued deletion
    that committed and then failed to invalidate would keep the erased
    name readable for the whole cache TTL.
    """
    invalidated: list[tuple[str, int]] = []

    class _Cache:
        def __init__(self, label: str) -> None:
            self.label = label

        def invalidate(self, user_id: int) -> None:
            invalidated.append((self.label, user_id))

    async def _sweep() -> tuple[int, list[int]]:
        return 2, [7, 8]

    monkeypatch.setattr(scheduler_jobs, "_run_erasure_sweep", _sweep)
    monkeypatch.setattr(scheduler_jobs, "user_mention_cache", _Cache("profile"))
    monkeypatch.setattr(scheduler_jobs, "effective_role_cache", _Cache("role"))

    asyncio.run(scheduler.process_erasure_queue())

    assert invalidated == [
        ("profile", 7),
        ("role", 7),
        ("profile", 8),
        ("role", 8),
    ]
