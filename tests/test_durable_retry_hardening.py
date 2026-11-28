# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Durable retries respect Telegram's cooldown and permanent refusals."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any

import pytest
from pyrogram.errors import ChatAdminRequired, FloodWait

from tcbot import database as db
from tcbot.modules.helper.pipelines import moderation_enforcement as enforcement
from tcbot.modules.helper.pipelines.errors import exceptions


def test_flood_wait_delay_uses_the_requested_seconds() -> None:
    assert exceptions.flood_wait_delay(FloodWait(900)) == timedelta(seconds=900)
    assert exceptions.flood_wait_delay(RuntimeError("down")) is None
    assert exceptions.flood_wait_delay(FloodWait(0)) is None
    assert exceptions.flood_wait_delay(FloodWait(exceptions._MAX_FLOOD_WAIT_S + 1)) == (
        timedelta(seconds=exceptions._MAX_FLOOD_WAIT_S)
    )


def test_a_permission_denial_is_recognized() -> None:
    assert exceptions.is_permission_denial(ChatAdminRequired()) is True
    assert exceptions.is_permission_denial(RuntimeError("chat admin required")) is False


def test_enforcement_retry_waits_for_the_flood_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[dict[str, Any]] = []

    async def _complete(_target_id: int, **kwargs: Any) -> None:
        seen.append(kwargs)

    monkeypatch.setattr(db.enforcement_ledger, "complete_target", _complete)

    asyncio.run(
        enforcement._record_target(
            {"id": 9, "attempt_count": 1},
            FloodWait(900),
        )
    )

    assert len(seen) == 1
    assert seen[0]["status"] == "failed"
    assert seen[0]["retry_after"] == timedelta(seconds=900)


def test_enforcement_retry_deadline_uses_the_database_clock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A retry deadline must come from PostgreSQL now(), not the host clock.

    The claim, report, and requeue statements all compare the deadline with
    the database clock. Computing it on the host made a skew delay or
    prematurely admit a federation delivery.
    """
    seen: list[dict[str, Any]] = []

    class _Session:
        async def scalar(self, _stmt: object, _params: object) -> int:
            return 1

        async def execute(self, _stmt: object, params: dict[str, Any]) -> None:
            seen.append(params)

    async def _transaction(work: Any) -> None:
        await work(_Session())

    monkeypatch.setattr(db.enforcement_ledger, "run_transaction", _transaction)

    asyncio.run(
        db.enforcement_ledger.complete_target(
            9,
            status="failed",
            outcome="failed",
            retry_after=timedelta(seconds=900),
        )
    )

    assert "now() + make_interval(" in str(db.enforcement_ledger._TARGET_UPDATE)
    assert "CAST(:retry_after_seconds AS double precision)" in str(
        db.enforcement_ledger._TARGET_UPDATE
    )
    assert "WHEN CAST(:retry_after_seconds AS double precision) IS NOT NULL" in str(
        db.enforcement_ledger._TARGET_UPDATE
    )
    assert all("next_retry_at" not in params for params in seen)
    assert seen[-1]["retry_after_seconds"] == 900.0

    seen.clear()
    asyncio.run(
        db.enforcement_ledger.complete_target(
            9, status="succeeded", outcome="succeeded"
        )
    )
    assert seen[-1]["retry_after_seconds"] is None

    seen.clear()
    asyncio.run(
        db.enforcement_ledger.complete_target(
            9,
            status="failed",
            outcome="failed",
            retry_after=timedelta(milliseconds=500),
        )
    )
    assert seen[-1]["retry_after_seconds"] == 0.5
