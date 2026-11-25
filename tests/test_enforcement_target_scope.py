# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Enforcement targets must exclude inactive chats other than the primary group."""

from __future__ import annotations

import asyncio
import dataclasses
from typing import Any

from tcbot import cfg
from tcbot.database import enforcement_ledger


def test_queue_run_filters_inactive_non_primary_targets(
    monkeypatch: Any,
) -> None:
    """A stale callback origin in a disconnected chat must not be queued."""
    executed: list[tuple[str, dict[str, Any]]] = []

    class _Result:
        def first(self) -> tuple[int]:
            return (5,)

    class _Session:
        async def execute(self, stmt: Any, params: dict[str, Any] | None = None) -> Any:
            executed.append((str(stmt), params or {}))
            return _Result()

        async def scalar(self, stmt: Any, params: dict[str, Any] | None = None) -> int:
            return 5

    monkeypatch.setattr(
        enforcement_ledger, "cfg", dataclasses.replace(cfg, main_group=-100)
    )

    asyncio.run(
        enforcement_ledger.queue_run(
            _Session(),  # type: ignore[arg-type]
            action_id=1,
            operation="apply",
            idempotency_key="scope-test",
            requested_by_user_id=None,
            chat_ids=[-100, -200, 0],
        )
    )

    target_sql, target_params = executed[-1]
    assert "cc.is_active OR cc.chat_id = :primary_chat_id" in target_sql
    assert target_params["primary_chat_id"] == -100
    assert target_params["chat_ids"] == [-100, -200]
