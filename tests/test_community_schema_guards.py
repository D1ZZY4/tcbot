# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""The database guards that protect the moderation decisions.

The application validates a decision before it writes it, and the trigger
that sits under the table is the last guard: a state that must not exist
cannot reach the database, even when two workers race. The contracts
below pin that guard, because a guard that quietly stops guarding is the
kind of defect no application test can see.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy import text

from tcbot.database import engine as engine_module
from tests.postgres_support import reset_community, seed_chats, seed_users

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

# * Every test in this module needs a real PostgreSQL server.
pytestmark = [pytest.mark.postgres]


@pytest.fixture
async def community(postgres_db: str) -> AsyncIterator[str]:
    """Start from an empty community with one connected group."""
    await reset_community()
    await seed_users(1, 2, 3)
    await seed_chats(-1001)
    yield postgres_db
    await reset_community()


async def _run(statement: str, **params: object) -> None:
    """Run one statement on the shared engine."""
    await engine_module.run(text(statement).bindparams(**params))


async def _fetch_one(statement: str, **params: object) -> Any:
    """Return the first column of the first row of one statement."""
    return await engine_module.fetch_value(text(statement).bindparams(**params))


async def _fetch_all(statement: str, **params: object) -> list[dict[str, Any]]:
    """Return every row of one statement."""
    return await engine_module.fetch_all(text(statement).bindparams(**params))


async def _open_case(user_id: int, *, requires_evidence: bool = False) -> int:
    """Open a case for *user_id* and return its id."""
    row = await engine_module.fetch_one(
        text(
            "INSERT INTO moderation_cases "
            "(subject_user_id, case_type, title, requires_evidence) "
            "VALUES (:user_id, 'rule_violation', 'case', :evidence) RETURNING id"
        ).bindparams(user_id=user_id, evidence=requires_evidence)
    )
    assert row is not None
    return int(row["id"])


async def _open_ban(
    user_id: int,
    *,
    case_id: int | None = None,
    origin: str = "automated",
    status: str = "active",
    external_ref: str = "ban00000001",
    supersedes: int | None = None,
) -> int:
    """Write one ban decision and return its id."""
    case = case_id if case_id is not None else await _open_case(user_id)
    row = await engine_module.fetch_one(
        text(
            "INSERT INTO moderation_actions "
            "(action_type, scope_type, target_user_id, actor_user_id, reason, "
            " status, external_ref, case_id, action_origin, created_at, "
            " supersedes_action_id) "
            "VALUES ('ban', 'community', :user_id, 1, 'reason', :status, "
            " :ref, :case_id, :origin, now(), :supersedes) RETURNING id"
        ).bindparams(
            user_id=user_id,
            status=status,
            ref=external_ref,
            case_id=case,
            origin=origin,
            supersedes=supersedes,
        )
    )
    assert row is not None
    return int(row["id"])


# ───────────────────────── The facts of a decision ───────────────────────── #


async def test_the_public_handle_of_a_decision_never_changes(community: str) -> None:
    """The appeal link carries the handle, so it may not be rewritten."""
    action_id = await _open_ban(2)

    with pytest.raises(Exception, match="Moderation action facts are immutable"):
        await _run(
            "UPDATE moderation_actions SET external_ref = 'otherhandle1' WHERE id = :id",
            id=action_id,
        )


async def test_the_reason_of_a_decision_never_changes(community: str) -> None:
    """The reason is the evidence of the decision, so it is immutable."""
    action_id = await _open_ban(2)

    with pytest.raises(Exception, match="Moderation action facts are immutable"):
        await _run(
            "UPDATE moderation_actions SET reason = 'a different reason' WHERE id = :id",
            id=action_id,
        )


async def test_a_re_ban_can_be_revoked_afterwards(community: str) -> None:
    """A re-ban is a decision like any other, so it can be revoked."""
    first = await _open_ban(2, external_ref="ban00000002")
    case_id = await _fetch_one(
        "SELECT case_id FROM moderation_actions WHERE id = :id", id=first
    )
    # * The re-ban names the decision it replaces, and the guard
    # * supersedes that decision.
    second = await _open_ban(
        2, case_id=int(case_id), external_ref="ban00000003", supersedes=first
    )

    # * The re-ban supersedes the decision it replaces.
    status = await _fetch_one(
        "SELECT status FROM moderation_actions WHERE id = :id", id=first
    )
    assert status == "superseded"

    await _run(
        "UPDATE moderation_actions SET status = 'revoked', revoked_at = now() "
        "WHERE id = :id",
        id=second,
    )
    status = await _fetch_one(
        "SELECT status FROM moderation_actions WHERE id = :id", id=second
    )
    assert status == "revoked"


async def test_an_expired_decision_can_still_be_updated(community: str) -> None:
    """Touching a decision that ran out does not fail with a database error."""
    case_id = await _open_case(2)
    row = await engine_module.fetch_one(
        text(
            "INSERT INTO moderation_actions "
            "(action_type, scope_type, target_user_id, actor_user_id, reason, "
            " status, external_ref, case_id, action_origin, created_at, expires_at) "
            "VALUES ('ban', 'community', 2, 1, 'reason', 'active', 'ban00000004', "
            " :case_id, 'automated', now() - interval '2 days', "
            " now() - interval '1 day') RETURNING id"
        ).bindparams(case_id=case_id)
    )
    assert row is not None

    await _run(
        'UPDATE moderation_actions SET metadata = metadata || \'{"note": "touched"}\' '
        "WHERE id = :id",
        id=int(row["id"]),
    )


# ───────────────────────── The group registry ───────────────────────── #


async def test_only_a_group_can_be_managed(community: str) -> None:
    """A channel is not a group of the community."""
    await _run(
        "INSERT INTO telegram_chats (chat_id, chat_type) VALUES (-500, 'channel')"
    )

    with pytest.raises(Exception, match="must be Telegram groups or supergroups"):
        await _run("INSERT INTO connected_chats (chat_id) VALUES (-500)")


async def test_a_disconnected_group_keeps_its_decisions(community: str) -> None:
    """A group that is no longer managed keeps the decisions of its history."""
    case_id = await _open_case(3)
    await _run(
        "INSERT INTO moderation_actions "
        "(action_type, scope_type, target_user_id, actor_user_id, reason, "
        " chat_id, origin_chat_id, status, external_ref, case_id, action_origin) "
        "VALUES ('warn', 'chat', 3, 1, 'reason', -1001, -1001, 'completed', "
        " 'warn0000001', :case_id, 'system')",
        case_id=case_id,
    )
    await _run("UPDATE connected_chats SET is_active = false WHERE chat_id = -1001")

    count = await _fetch_one(
        "SELECT count(*) FROM moderation_actions WHERE action_type = 'warn'"
    )
    assert count == 1

    # * A new decision for a group that is no longer managed is refused.
    with pytest.raises(Exception, match="requires an active connected chat"):
        await _run(
            "INSERT INTO moderation_actions "
            "(action_type, scope_type, target_user_id, actor_user_id, reason, "
            " chat_id, origin_chat_id, status, external_ref, case_id, action_origin) "
            "VALUES ('warn', 'chat', 3, 1, 'reason', -1001, -1001, 'completed', "
            " 'warn0000002', :case_id, 'system')",
            case_id=case_id,
        )


# ───────────────────────── The role assignments ───────────────────────── #


async def test_the_facts_of_a_role_assignment_never_change(community: str) -> None:
    """A demotion revokes the assignment; it never rewrites it."""
    await _run(
        "INSERT INTO role_assignments (user_id, role_key, status) "
        "VALUES (2, 'moderator', 'active')"
    )
    assignment_id = await _fetch_one(
        "SELECT id FROM role_assignments WHERE user_id = 2 AND role_key = 'moderator'"
    )

    with pytest.raises(Exception, match="Role assignment facts are immutable"):
        await _run(
            "UPDATE role_assignments SET role_key = 'admin' WHERE id = :id",
            id=assignment_id,
        )


async def test_a_user_holds_one_active_role(community: str) -> None:
    """A second active role for the same user is refused."""
    await _run(
        "INSERT INTO role_assignments (user_id, role_key, status) "
        "VALUES (2, 'moderator', 'active')"
    )

    with pytest.raises(Exception, match="uq_role_assignments_active_user"):
        await _run(
            "INSERT INTO role_assignments (user_id, role_key, status) "
            "VALUES (2, 'developer', 'active')"
        )


async def test_the_community_holds_one_active_owner(community: str) -> None:
    """A second active owner is refused."""
    await _run(
        "INSERT INTO role_assignments (user_id, role_key, status) "
        "VALUES (1, 'owner', 'active')"
    )

    with pytest.raises(Exception, match="uq_role_assignments_active_owner"):
        await _run(
            "INSERT INTO role_assignments (user_id, role_key, status) "
            "VALUES (2, 'owner', 'active')"
        )


# ───────────────────────── The evidence archive ───────────────────────── #


async def test_a_batch_cannot_arrive_already_closed(community: str) -> None:
    """A closed batch needs its items, so it cannot be inserted closed."""
    case_id = await _open_case(2)

    with pytest.raises(
        Exception, match="Evidence upload must be created in queued state"
    ):
        await _run(
            "INSERT INTO moderation_evidence_uploads "
            "(case_id, destination_chat_id, expected_item_count, is_required, status) "
            "VALUES (:case_id, -1001, 2, true, 'completed')",
            case_id=case_id,
        )


async def test_a_manual_ban_needs_its_archived_proof(community: str) -> None:
    """The proof of a manual ban is not optional."""
    case_id = await _open_case(2, requires_evidence=True)

    with pytest.raises(
        Exception, match="requires an explicitly linked completed evidence upload"
    ):
        await _run(
            "INSERT INTO moderation_actions "
            "(action_type, scope_type, target_user_id, actor_user_id, reason, "
            " status, external_ref, case_id, action_origin) "
            "VALUES ('ban', 'community', 2, 1, 'reason', 'active', 'ban00000005', "
            " :case_id, 'manual')",
            case_id=case_id,
        )


async def test_the_order_of_the_archived_items_is_fixed(community: str) -> None:
    """A closed batch keeps the order its items were collected in."""
    case_id = await _open_case(2)
    upload_id = await engine_module.fetch_one(
        text(
            "INSERT INTO moderation_evidence_uploads "
            "(case_id, destination_chat_id, expected_item_count, is_required, status) "
            "VALUES (:case_id, -1001, 1, true, 'queued') RETURNING id"
        ).bindparams(case_id=case_id)
    )
    assert upload_id is not None
    # * The worker claims the batch before it archives the items.
    await _run(
        "UPDATE moderation_evidence_uploads SET status = 'uploading' WHERE id = :id",
        id=int(upload_id["id"]),
    )
    item_id = await engine_module.fetch_one(
        text(
            "INSERT INTO moderation_evidence_items "
            "(upload_id, destination_chat_id, archive_message_id, media_type, item_order) "
            "VALUES (:upload, -1001, 42, 'photo', 0) RETURNING id"
        ).bindparams(upload=int(upload_id["id"]))
    )
    assert item_id is not None

    with pytest.raises(
        Exception, match="Archived moderation evidence items are append-only"
    ):
        await _run(
            "UPDATE moderation_evidence_items SET item_order = 5 WHERE id = :id",
            id=int(item_id["id"]),
        )


# ───────────────────────── The enforcement work ───────────────────────── #


async def test_a_target_starts_pending(community: str) -> None:
    """A target that arrives finished would report a delivery that never happened."""
    action_id = await _open_ban(2, external_ref="ban00000006")
    run_id = await engine_module.fetch_one(
        text(
            "INSERT INTO moderation_enforcement_runs "
            "(action_id, operation, idempotency_key) "
            "VALUES (:action, 'apply', 'run-00000001') RETURNING id"
        ).bindparams(action=action_id)
    )
    assert run_id is not None

    with pytest.raises(
        Exception, match="Enforcement targets must start pending and untouched"
    ):
        await _run(
            "INSERT INTO moderation_enforcement_targets (run_id, chat_id, status) "
            "VALUES (:run, -1001, 'succeeded')",
            run=int(run_id["id"]),
        )


async def test_a_retry_waits_for_its_deadline(community: str) -> None:
    """A retry before the deadline is refused, and it raises the attempt count."""
    action_id = await _open_ban(2, external_ref="ban00000007")
    run_id = await engine_module.fetch_one(
        text(
            "INSERT INTO moderation_enforcement_runs "
            "(action_id, operation, idempotency_key) "
            "VALUES (:action, 'apply', 'run-00000002') RETURNING id"
        ).bindparams(action=action_id)
    )
    assert run_id is not None
    target_id = await engine_module.fetch_one(
        text(
            "INSERT INTO moderation_enforcement_targets (run_id, chat_id) "
            "VALUES (:run, -1001) RETURNING id"
        ).bindparams(run=int(run_id["id"]))
    )
    assert target_id is not None
    target = int(target_id["id"])

    await _run(
        "UPDATE moderation_enforcement_targets "
        "SET status = 'in_progress', attempt_count = 1 WHERE id = :id",
        id=target,
    )
    await _run(
        "UPDATE moderation_enforcement_targets "
        "SET status = 'failed', next_retry_at = now() + interval '1 hour' "
        "WHERE id = :id",
        id=target,
    )

    with pytest.raises(
        Exception, match="Enforcement target retry deadline has not arrived"
    ):
        await _run(
            "UPDATE moderation_enforcement_targets "
            "SET status = 'in_progress', attempt_count = 2 WHERE id = :id",
            id=target,
        )

    # * Once the deadline has passed, the retry goes through, and the
    # * trigger raises the attempt count on its own: a caller cannot
    # * lower it.
    await _run(
        "UPDATE moderation_enforcement_targets "
        "SET next_retry_at = now() - interval '1 minute' WHERE id = :id",
        id=target,
    )
    await _run(
        "UPDATE moderation_enforcement_targets "
        "SET status = 'in_progress', attempt_count = 1 WHERE id = :id",
        id=target,
    )
    attempt_count = await _fetch_one(
        "SELECT attempt_count FROM moderation_enforcement_targets WHERE id = :id",
        id=target,
    )
    assert attempt_count == 2


async def test_the_run_status_follows_its_targets(community: str) -> None:
    """A run whose targets all failed is failed, not partial."""
    action_id = await _open_ban(2, external_ref="ban00000008")
    run_id = await engine_module.fetch_one(
        text(
            "INSERT INTO moderation_enforcement_runs "
            "(action_id, operation, idempotency_key) "
            "VALUES (:action, 'apply', 'run-00000003') RETURNING id"
        ).bindparams(action=action_id)
    )
    assert run_id is not None
    target_id = await engine_module.fetch_one(
        text(
            "INSERT INTO moderation_enforcement_targets (run_id, chat_id) "
            "VALUES (:run, -1001) RETURNING id"
        ).bindparams(run=int(run_id["id"]))
    )
    assert target_id is not None
    target = int(target_id["id"])

    await _run(
        "UPDATE moderation_enforcement_targets "
        "SET status = 'in_progress', attempt_count = 1 WHERE id = :id",
        id=target,
    )
    await _run(
        "UPDATE moderation_enforcement_targets SET status = 'failed' WHERE id = :id",
        id=target,
    )
    status = await _fetch_one(
        "SELECT status FROM moderation_enforcement_runs WHERE id = :id",
        id=int(run_id["id"]),
    )
    assert status == "failed"


# ───────────────────────── The audit trail ───────────────────────── #


async def test_an_audit_event_points_at_a_live_row(community: str) -> None:
    """A dangling reference is refused, so the trail stays checkable."""
    with pytest.raises(Exception, match="that does not exist"):
        await _run(
            "INSERT INTO audit_events (event_key, entity_type, entity_id) "
            "VALUES ('test.event', 'moderation_action', '999999999')"
        )

    action_id = await _open_ban(2, external_ref="ban00000009")
    await _run(
        "INSERT INTO audit_events (event_key, entity_type, entity_id) "
        "VALUES ('test.event', 'moderation_action', :id)",
        id=action_id,
    )


async def test_the_audit_trail_cannot_be_rewritten(community: str) -> None:
    """An audit event is a record of what happened, never a draft."""
    await _run(
        "INSERT INTO audit_events (event_key, entity_type, entity_id) "
        "VALUES ('test.event', 'retention_policy', 'audit_events')"
    )

    with pytest.raises(Exception, match="append-only"):
        await _run(
            "UPDATE audit_events SET event_key = 'other.event' "
            "WHERE event_key = 'test.event'"
        )


async def test_the_attempt_history_follows_the_retention_policy(community: str) -> None:
    """A fresh attempt is protected, an expired one is not."""
    action_id = await _open_ban(2, external_ref="ban00000010")
    run_id = await engine_module.fetch_one(
        text(
            "INSERT INTO moderation_enforcement_runs "
            "(action_id, operation, idempotency_key) "
            "VALUES (:action, 'apply', 'run-00000004') RETURNING id"
        ).bindparams(action=action_id)
    )
    assert run_id is not None
    target_id = await engine_module.fetch_one(
        text(
            "INSERT INTO moderation_enforcement_targets (run_id, chat_id) "
            "VALUES (:run, -1001) RETURNING id"
        ).bindparams(run=int(run_id["id"]))
    )
    assert target_id is not None
    target = int(target_id["id"])
    # * An attempt belongs to a target that is in progress: the number
    # * of the attempt has to match the attempt count of the target.
    await _run(
        "UPDATE moderation_enforcement_targets SET status = 'in_progress' WHERE id = :id",
        id=target,
    )
    attempt_id = await engine_module.fetch_one(
        text(
            "INSERT INTO moderation_enforcement_attempts "
            "(target_id, attempt_number, outcome, attempted_at) "
            "VALUES (:target, 1, 'failed', now()) RETURNING id"
        ).bindparams(target=target)
    )
    assert attempt_id is not None
    attempt = int(attempt_id["id"])

    with pytest.raises(Exception, match="append-only"):
        await _run(
            "DELETE FROM moderation_enforcement_attempts WHERE id = :id", id=attempt
        )

    # * The retention window is 180 days, so an attempt that is older
    # * than that may go. The attempt history itself is append-only, so
    # * the old row is written with its old moment. The second attempt
    # * belongs to the second try of the target.
    await _run(
        "UPDATE moderation_enforcement_targets SET status = 'failed' WHERE id = :id",
        id=target,
    )
    await _run(
        "UPDATE moderation_enforcement_targets SET status = 'in_progress' WHERE id = :id",
        id=target,
    )
    old_id = await engine_module.fetch_one(
        text(
            "INSERT INTO moderation_enforcement_attempts "
            "(target_id, attempt_number, outcome, attempted_at) "
            "VALUES (:target, 2, 'failed', now() - interval '200 days') RETURNING id"
        ).bindparams(target=target)
    )
    assert old_id is not None
    await _run(
        "DELETE FROM moderation_enforcement_attempts WHERE id = :id",
        id=int(old_id["id"]),
    )


# ───────────────────────── The scheduled jobs ───────────────────────── #


async def test_the_job_registry_carries_the_known_jobs(community: str) -> None:
    """Every job of the registry is registered and scheduled."""
    keys = await _fetch_all(
        "SELECT job_key, schedule_spec FROM scheduled_jobs ORDER BY job_key"
    )
    registered = {str(row["job_key"]) for row in keys}
    assert registered == {
        "moderation.expire",
        "role.expire",
        "enforcement.reconcile",
        "scheduler.drift",
        "user.erasure",
        "retention.sweep",
    }
    for row in keys:
        assert str(row["schedule_spec"]).strip()


async def test_a_repeated_tick_does_not_claim_the_job_twice(community: str) -> None:
    """The run key makes a second tick in the same slot a no-op."""
    first = await _fetch_one(
        "SELECT scheduled_job_claim('moderation.expire', 'verify-run-1', 'cron')"
    )
    assert first is not None
    second = await _fetch_one(
        "SELECT scheduled_job_claim('moderation.expire', 'verify-run-1', 'cron')"
    )
    assert second is None


async def test_a_disabled_job_is_never_claimed(community: str) -> None:
    """The kill switch of a job is honoured by the claim."""
    await _run(
        "UPDATE scheduled_jobs SET is_enabled = false WHERE job_key = 'role.expire'"
    )

    claimed = await _fetch_one(
        "SELECT scheduled_job_claim('role.expire', 'verify-run-2', 'cron')"
    )
    assert claimed is None


# ───────────────────────── The broadcast audience ───────────────────────── #


async def test_an_unknown_audience_mode_is_refused(community: str) -> None:
    """A typo in the audience filter must not broadcast to every group."""
    # * The filter is validated when the campaign is written, so a
    # * campaign with an unknown mode never reaches the queue.
    with pytest.raises(Exception, match="Unsupported broadcast audience mode"):
        await _run(
            "INSERT INTO broadcast_campaigns "
            "(title, idempotency_key, audience_filter) "
            "VALUES ('campaign', 'verify-campaign-1', '{\"mode\": \"all_actve\"}')"
        )


async def test_the_audience_snapshot_names_the_active_groups(community: str) -> None:
    """A campaign reaches the groups that are managed when it is queued."""
    await seed_chats(-1002)
    campaign_id = await engine_module.fetch_one(
        text(
            "INSERT INTO broadcast_campaigns (title, idempotency_key, audience_filter) "
            "VALUES ('campaign', 'verify-campaign-2', '{\"mode\": \"all_active\"}') "
            "RETURNING id"
        )
    )
    assert campaign_id is not None

    await _run("SELECT queue_broadcast_campaign(:id)", id=int(campaign_id["id"]))
    targets = await _fetch_all(
        "SELECT chat_id FROM broadcast_targets WHERE campaign_id = :id",
        id=int(campaign_id["id"]),
    )
    assert {int(row["chat_id"]) for row in targets} == {-1001, -1002}
