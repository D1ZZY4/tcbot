# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Expired decisions queue a revoke run that a worker can claim and close."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

import pytest

from tcbot.database import enforcement_db, scheduler
from tcbot.database.base import moderation_enforcement_runs
from tcbot.database.engine import fetch_one
from tcbot.utils.time_and_date import utc_now
from tests.postgres_support import (
    reset_community,
    seed_action,
    seed_case,
    seed_chats,
    seed_users,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


@pytest.fixture
async def enforcement_db_ready(postgres_db: str) -> AsyncIterator[str]:
    """Start from an empty community with one connected group."""
    await reset_community()
    await seed_users(7, 9)
    await seed_chats(-1001)
    yield postgres_db
    await reset_community()


async def test_an_expired_ban_is_claimed_and_completed(
    enforcement_db_ready: str,
) -> None:
    """The queued run exposes its action and group, then closes."""
    now = utc_now()
    case_id = await seed_case(9, opened_by_user_id=7)
    action_id = await seed_action(
        "ban",
        9,
        actor_user_id=7,
        case_id=case_id,
        created_at=now - timedelta(hours=2),
        expires_at=now - timedelta(hours=1),
    )

    await scheduler.expire_due_decisions()

    runs = await enforcement_db.claim_runs(limit=10)
    assert len(runs) == 1
    run_id = int(str(runs[0]["id"]))
    assert int(str(runs[0]["action_id"])) == action_id

    action = await enforcement_db.load_run_action(run_id)
    assert action is not None
    assert action["action_type"] == "ban"
    assert action["target_user_id"] == 9
    assert action["action_status"] == "expired"

    targets = await enforcement_db.claim_targets(run_id)
    assert [target["chat_id"] for target in targets] == [-1001]

    await enforcement_db.complete_target(
        int(str(targets[0]["id"])), status="succeeded", outcome="succeeded"
    )

    row = await fetch_one(
        moderation_enforcement_runs.select().where(
            moderation_enforcement_runs.c.id == run_id
        )
    )
    assert row is not None
    assert row["status"] == "completed"
    assert row["succeeded_count"] == 1


async def test_a_stale_running_run_returns_to_the_queue(
    enforcement_db_ready: str,
) -> None:
    """A worker crash must not strand the run in running forever."""
    now = utc_now()
    case_id = await seed_case(9, opened_by_user_id=7)
    await seed_action(
        "ban",
        9,
        actor_user_id=7,
        case_id=case_id,
        created_at=now - timedelta(hours=2),
        expires_at=now - timedelta(hours=1),
    )
    await scheduler.expire_due_decisions()
    runs = await enforcement_db.claim_runs(limit=1)
    run_id = int(str(runs[0]["id"]))

    await enforcement_db.requeue_stale_runs(timedelta(seconds=0))

    again = await enforcement_db.claim_runs(limit=1)
    assert [int(str(run["id"])) for run in again] == [run_id]


async def test_a_failed_target_is_retried_after_its_deadline(
    enforcement_db_ready: str,
) -> None:
    """A retryable delivery failure reopens its run when the deadline arrives.

    The target trigger refuses in_progress -> pending, so the failure has
    to be recorded as failed with a due deadline; the run statement then
    re-queues the closed run and the next tick claims the target again.
    """
    now = utc_now()
    case_id = await seed_case(9, opened_by_user_id=7)
    await seed_action(
        "ban",
        9,
        actor_user_id=7,
        case_id=case_id,
        created_at=now - timedelta(hours=2),
        expires_at=now - timedelta(hours=1),
    )
    await scheduler.expire_due_decisions()

    runs = await enforcement_db.claim_runs(limit=1)
    run_id = int(str(runs[0]["id"]))
    targets = await enforcement_db.claim_targets(run_id)
    target_id = int(str(targets[0]["id"]))

    await enforcement_db.complete_target(
        target_id,
        status="failed",
        outcome="failed",
        error_kind="TimedOut",
        error_detail="network down",
        retry_after=timedelta(seconds=0),
    )

    await enforcement_db.requeue_stale_runs(timedelta(seconds=0))

    again = await enforcement_db.claim_runs(limit=1)
    assert [int(str(run["id"])) for run in again] == [run_id]
    claimed = await enforcement_db.claim_targets(run_id)
    assert [int(str(target["id"])) for target in claimed] == [target_id]
