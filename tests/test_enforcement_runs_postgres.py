# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Durable enforcement runs: atomic decisions, per-group delivery, repair."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, cast

import pytest
from sqlalchemy import select

from tcbot import cfg
from tcbot.database import (
    bans_db,
    enforcement_db,
    groups_db,
    kicks_db,
    mutes_db,
    notifications_db,
)
from tcbot.database import engine as engine_module
from tcbot.database.base import (
    moderation_actions,
    moderation_appeals,
    moderation_enforcement_runs,
    moderation_enforcement_targets,
    moderation_notification_tasks,
    telegram_chats,
    telegram_users,
)
from tcbot.database.types import as_int
from tests.postgres_support import reset_community, seed_chats, seed_users

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from tcbot.database.documents import EvidenceItemDoc


@pytest.fixture
async def run_db(postgres_db: str) -> AsyncIterator[str]:
    await reset_community()
    await seed_users(7)
    await seed_chats(-1001, cfg.proofs[0])
    yield postgres_db
    await reset_community()


def _proof() -> list[EvidenceItemDoc]:
    return [{"media_type": "photo", "archive_message_id": 501}]


async def test_unban_revokes_and_queues_the_delivery(run_db: str) -> None:
    await bans_db.create_ban(
        42,
        "spam",
        7,
        501,
        0,
        "liferun0001",
        destination_chat_id=cfg.proofs[0],
        proof_items=_proof(),
        proof_expected_count=1,
    )
    await bans_db.submit_appeal("liferun0001", 42, "please", 900)

    revoked, run_id = await bans_db.revoke_ban_and_queue_unban(
        42,
        8,
        [-1001],
        review_chat_id=-1001,
        review_message_id=900,
    )

    assert revoked == 1
    assert run_id is not None
    actor = await engine_module.fetch_one(
        select(telegram_users.c.user_id).where(telegram_users.c.user_id == 8)
    )
    assert actor == {"user_id": 8}
    action = await engine_module.fetch_one(
        select(moderation_actions.c.status).where(
            moderation_actions.c.external_ref == "liferun0001"
        )
    )
    assert action == {"status": "revoked"}
    appeal = await engine_module.fetch_one(
        select(moderation_appeals.c.status).where(
            moderation_appeals.c.action_id
            == select(moderation_actions.c.id)
            .where(moderation_actions.c.external_ref == "liferun0001")
            .scalar_subquery()
        )
    )
    assert appeal == {"status": "withdrawn"}
    target = await engine_module.fetch_one(
        select(
            moderation_enforcement_targets.c.chat_id,
            moderation_enforcement_targets.c.status,
        ).where(moderation_enforcement_targets.c.run_id == run_id)
    )
    assert target == {"chat_id": -1001, "status": "pending"}
    card = await engine_module.fetch_one(
        select(
            moderation_notification_tasks.c.chat_id,
            moderation_notification_tasks.c.message_id,
            moderation_notification_tasks.c.state,
        ).where(
            moderation_notification_tasks.c.action_id
            == select(moderation_actions.c.id)
            .where(moderation_actions.c.external_ref == "liferun0001")
            .scalar_subquery()
        )
    )
    assert card == {"chat_id": -1001, "message_id": 900, "state": "pending"}

    claimed = await enforcement_db.claim_run(run_id)
    assert claimed is not None
    targets = await enforcement_db.claim_targets(run_id)
    assert [as_int(target["chat_id"]) for target in targets] == [-1001]
    await enforcement_db.complete_target(
        as_int(targets[0]["id"]), status="succeeded", outcome="succeeded"
    )
    report = await enforcement_db.run_report(run_id)
    assert report is not None
    assert report["status"] == "completed"
    assert report["succeeded_count"] == 1
    assert report["failed_count"] == 0
    report_targets = cast("list[dict[str, object]]", report["targets"])
    assert report_targets[0]["title"] == "Group -1001"

    again = await bans_db.revoke_ban_and_queue_unban(42, 7, [-1001])
    assert again == (0, None)


async def test_a_revoke_run_sees_a_newer_active_decision(run_db: str) -> None:
    """A re-ban after an unban marks the old revoke as superseded.

    The worker has to know that the target is restricted again, so an old
    retried revoke cannot lift the newer ban.
    """
    await bans_db.create_ban(
        42,
        "first",
        7,
        501,
        0,
        "liferun0101",
        destination_chat_id=cfg.proofs[0],
        proof_items=_proof(),
        proof_expected_count=1,
    )
    _, run_id = await bans_db.revoke_ban_and_queue_unban(42, 8, [-1001])
    assert run_id is not None

    await bans_db.create_ban(
        42,
        "second",
        7,
        502,
        0,
        "liferun0102",
        destination_chat_id=cfg.proofs[0],
        proof_items=_proof(),
        proof_expected_count=1,
    )

    action = await enforcement_db.load_run_action(run_id)
    assert action is not None
    assert action["newer_active"] is True
    assert action["active_ban"] is True


async def test_appeal_approval_is_one_decision(run_db: str) -> None:
    await bans_db.create_ban(
        42,
        "spam",
        7,
        501,
        0,
        "liferun0002",
        destination_chat_id=cfg.proofs[0],
        proof_items=_proof(),
        proof_expected_count=1,
    )
    await bans_db.submit_appeal("liferun0002", 42, "please", 901)
    claimed = await bans_db.claim_appeal_decision("liferun0002", 901)
    assert claimed is True

    accepted, run_id = await bans_db.approve_appeal_and_queue_unban(
        "liferun0002", 7, "Owner", 7, [-1001]
    )

    assert accepted is True
    assert run_id is not None
    action = await engine_module.fetch_one(
        select(
            moderation_actions.c.status,
            moderation_actions.c.metadata,
        ).where(moderation_actions.c.external_ref == "liferun0002")
    )
    assert action is not None
    assert action["status"] == "revoked"
    assert "review_message_id" not in action["metadata"]
    appeal = await engine_module.fetch_one(
        select(
            moderation_appeals.c.status,
            moderation_appeals.c.reviewed_by_user_id,
        ).where(
            moderation_appeals.c.action_id
            == select(moderation_actions.c.id)
            .where(moderation_actions.c.external_ref == "liferun0002")
            .scalar_subquery()
        )
    )
    assert appeal == {"status": "accepted", "reviewed_by_user_id": 7}


async def test_a_ban_apply_run_is_queued_with_the_decision(run_db: str) -> None:
    ban = await bans_db.create_ban(
        42,
        "spam",
        7,
        501,
        0,
        "liferun0003",
        destination_chat_id=cfg.proofs[0],
        proof_items=_proof(),
        proof_expected_count=1,
        enforcement_chat_ids=[-1001],
    )

    run_id = ban.get("enforcement_run_id")
    assert isinstance(run_id, int)
    run = await engine_module.fetch_one(
        select(
            moderation_enforcement_runs.c.operation,
            moderation_enforcement_runs.c.status,
        ).where(moderation_enforcement_runs.c.id == run_id)
    )
    assert run == {"operation": "apply", "status": "queued"}
    target = await engine_module.fetch_one(
        select(moderation_enforcement_targets.c.chat_id).where(
            moderation_enforcement_targets.c.run_id == run_id
        )
    )
    assert target == {"chat_id": -1001}


async def test_a_mute_apply_run_keeps_the_requested_duration(run_db: str) -> None:
    _, run_id = await mutes_db.record_mute(
        43,
        -1001,
        "spam",
        7,
        requested_duration_seconds=3600,
        enforcement_chat_ids=[-1001],
    )

    assert isinstance(run_id, int)
    run = await engine_module.fetch_one(
        select(moderation_enforcement_runs.c.operation).where(
            moderation_enforcement_runs.c.id == run_id
        )
    )
    assert run == {"operation": "apply"}
    action = await engine_module.fetch_one(
        select(moderation_actions.c.metadata).where(
            moderation_actions.c.target_user_id == 43,
            moderation_actions.c.action_type == "mute",
        )
    )
    assert action is not None
    assert action["metadata"]["requested_duration_seconds"] == 3600


async def test_an_unmute_revokes_and_queues_the_restore(run_db: str) -> None:
    action_id, apply_run = await mutes_db.record_mute(
        43,
        -1001,
        "spam",
        7,
        enforcement_chat_ids=[-1001],
    )
    assert isinstance(apply_run, int)

    revoked, run_id = await mutes_db.revoke_mute_and_queue_unmute(43, 8, [-1001])

    assert revoked == 1
    assert isinstance(run_id, int)
    action = await engine_module.fetch_one(
        select(moderation_actions.c.status).where(moderation_actions.c.id == action_id)
    )
    assert action == {"status": "revoked"}
    run = await engine_module.fetch_one(
        select(
            moderation_enforcement_runs.c.operation,
            moderation_enforcement_runs.c.status,
        ).where(moderation_enforcement_runs.c.id == run_id)
    )
    assert run == {"operation": "revoke", "status": "queued"}
    target = await engine_module.fetch_one(
        select(moderation_enforcement_targets.c.chat_id).where(
            moderation_enforcement_targets.c.run_id == run_id
        )
    )
    assert target == {"chat_id": -1001}

    again = await mutes_db.revoke_mute_and_queue_unmute(43, 8, [-1001])
    assert again == (0, None)


async def test_review_card_outbox_round_trip(run_db: str) -> None:
    ban = await bans_db.create_ban(
        42,
        "spam",
        7,
        501,
        0,
        "liferun0004",
        destination_chat_id=cfg.proofs[0],
        proof_items=_proof(),
        proof_expected_count=1,
    )
    action_id = as_int(ban.get("id"))
    await notifications_db.enqueue_review_card_edit(action_id, -1001, 900)

    tasks = await notifications_db.claim_due_tasks(10, retry_after=timedelta(minutes=5))
    assert tasks
    task = tasks[0]
    assert as_int(task.get("action_id")) == action_id
    assert as_int(task.get("message_id")) == 900

    task_id = as_int(task.get("id"))
    await notifications_db.complete_task(task_id, state="sent")
    row = await engine_module.fetch_one(
        select(
            moderation_notification_tasks.c.state,
            moderation_notification_tasks.c.attempts,
        ).where(moderation_notification_tasks.c.id == task_id)
    )
    assert row == {"state": "sent", "attempts": 1}


async def test_a_kick_can_queue_its_unban_repair(run_db: str) -> None:
    kick_id = await kicks_db.log_kick(44, -1001, "spam", 7)

    run_id = await enforcement_db.queue_kick_unban_repair(kick_id, -1001, 7)

    assert run_id is not None
    run = await engine_module.fetch_one(
        select(
            moderation_enforcement_targets.c.chat_id,
        ).where(moderation_enforcement_targets.c.run_id == run_id)
    )
    assert run == {"chat_id": -1001}


async def test_a_kick_status_follows_its_delivery(run_db: str) -> None:
    """A failed kick is distinguishable, and its repair restores completed."""
    await seed_users(44)
    kick_id = await kicks_db.log_kick(44, -1001, "spam", 7)

    assert await kicks_db.mark_kick_failed(kick_id) is True
    status = await engine_module.fetch_value(
        select(moderation_actions.c.status).where(moderation_actions.c.id == kick_id)
    )
    assert status == "failed"

    assert await kicks_db.mark_kick_completed(kick_id) is True
    status = await engine_module.fetch_value(
        select(moderation_actions.c.status).where(moderation_actions.c.id == kick_id)
    )
    assert status == "completed"


async def test_an_exhausted_failed_target_can_be_re_driven(run_db: str) -> None:
    """An operator can retry a run whose automatic budget is spent."""
    ban = await bans_db.create_ban(
        42,
        "spam",
        7,
        501,
        0,
        "liferun0005",
        destination_chat_id=cfg.proofs[0],
        proof_items=_proof(),
        proof_expected_count=1,
        enforcement_chat_ids=[-1001],
    )
    run_id = ban.get("enforcement_run_id")
    assert isinstance(run_id, int)

    assert await enforcement_db.claim_run(run_id) is not None
    targets = await enforcement_db.claim_targets(run_id)
    assert len(targets) == 1
    await enforcement_db.complete_target(
        as_int(targets[0]["id"]),
        status="failed",
        outcome="failed",
        error_kind="Forbidden",
        error_detail="not enough rights",
    )

    report = await enforcement_db.run_report(run_id)
    assert report is not None
    assert report["status"] == "failed"
    listed = await enforcement_db.list_unsettled_runs()
    assert any(as_int(row.get("id")) == run_id for row in listed)

    repaired = await enforcement_db.redrive_run(run_id)
    assert repaired.state == "queued"
    assert repaired.targets == 1
    run = await engine_module.fetch_one(
        select(moderation_enforcement_runs.c.status).where(
            moderation_enforcement_runs.c.id == run_id
        )
    )
    assert run == {"status": "queued"}

    assert await enforcement_db.claim_run(run_id) is not None
    retried = await enforcement_db.claim_targets(run_id)
    assert len(retried) == 1
    assert as_int(retried[0]["attempt_count"]) == 2


async def test_a_repair_can_target_one_group(run_db: str) -> None:
    """A single chat id re-drives that group and leaves the others failed."""
    await seed_chats(-1002)
    ban = await bans_db.create_ban(
        42,
        "spam",
        7,
        501,
        0,
        "liferun0007",
        destination_chat_id=cfg.proofs[0],
        proof_items=_proof(),
        proof_expected_count=1,
        enforcement_chat_ids=[-1001, -1002],
    )
    run_id = ban.get("enforcement_run_id")
    assert isinstance(run_id, int)
    assert await enforcement_db.claim_run(run_id) is not None
    targets = await enforcement_db.claim_targets(run_id)
    assert len(targets) == 2
    for target in targets:
        await enforcement_db.complete_target(
            as_int(target["id"]),
            status="failed",
            outcome="failed",
            error_kind="Forbidden",
            error_detail="not enough rights",
        )

    repaired = await enforcement_db.redrive_run(run_id, chat_id=-1001)
    assert repaired.state == "queued"
    assert repaired.targets == 1

    rows = await engine_module.fetch_all(
        select(
            moderation_enforcement_targets.c.chat_id,
            moderation_enforcement_targets.c.next_retry_at,
        ).where(moderation_enforcement_targets.c.run_id == run_id)
    )
    retry_by_chat = {
        as_int(row["chat_id"]): row["next_retry_at"] is not None for row in rows
    }
    assert retry_by_chat == {-1001: True, -1002: False}


async def test_a_cancelled_run_is_not_re_driven(run_db: str) -> None:
    ban = await bans_db.create_ban(
        42,
        "spam",
        7,
        501,
        0,
        "liferun0006",
        destination_chat_id=cfg.proofs[0],
        proof_items=_proof(),
        proof_expected_count=1,
        enforcement_chat_ids=[-1001],
    )
    run_id = ban.get("enforcement_run_id")
    assert isinstance(run_id, int)
    assert await enforcement_db.claim_run(run_id) is not None
    await enforcement_db.cancel_run(run_id, error_detail="superseded")
    metadata = await engine_module.fetch_value(
        select(moderation_enforcement_runs.c.metadata).where(
            moderation_enforcement_runs.c.id == run_id
        )
    )
    assert metadata == {"cancel_reason": "superseded"}

    assert (await enforcement_db.redrive_run(run_id)).state == "cancelled"
    assert (await enforcement_db.redrive_run(999_999)).state == "missing"


async def test_a_destination_is_registered_without_rewriting_a_group(
    run_db: str,
) -> None:
    await groups_db.ensure_destinations([(-100555, False)])

    channel = await engine_module.fetch_one(
        select(telegram_chats.c.chat_type).where(telegram_chats.c.chat_id == -100555)
    )
    assert channel == {"chat_type": "channel"}

    await groups_db.ensure_destinations([(-1001, False)])

    group = await engine_module.fetch_one(
        select(telegram_chats.c.chat_type).where(telegram_chats.c.chat_id == -1001)
    )
    assert group == {"chat_type": "supergroup"}
