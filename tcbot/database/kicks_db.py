# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Group kick helpers over the moderation decision tables.

A kick is one decision in ``moderation_actions``. It is bound to the
group it happened in, so it never reaches the other managed groups.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from tcbot.database import moderation_db
from tcbot.database.base import moderation_actions
from tcbot.database.documents import ActionStatus, KickDoc
from tcbot.database.engine import (
    db_call,
    fetch_all,
    fetch_value,
    run,
    run_transaction,
)
from tcbot.database.types import ChatId, UserId
from tcbot.utils.logger import get_logger
from tcbot.utils.time_and_date import utc_now

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime

    from sqlalchemy.ext.asyncio import AsyncSession

    from tcbot.database.documents import EvidenceItemDoc

log = get_logger(__name__)

# ──────────────────────────── Table ─────────────────────────────── #
# * The surrogate primary key stays out of the returned documents: the
# * helpers expose the community fields, not the storage identity.
_KICK_COLUMNS = (
    moderation_actions.c.id,
    moderation_actions.c.target_user_id,
    moderation_actions.c.actor_user_id,
    moderation_actions.c.reason,
    moderation_actions.c.chat_id,
    moderation_actions.c.created_at,
    moderation_actions.c.status,
    moderation_actions.c.case_id,
)

# ──────────────────────────── Mutations ─────────────────────────── #
# * Functions that create or modify kick decisions.
# * Used exclusively for audit logging of moderation actions


async def log_kick(
    user_id: int,
    chat_id: int,
    reason: str,
    admin_id: int,
    *,
    proof_items: Sequence[EvidenceItemDoc] | None = None,
    proof_expected_count: int = 0,
    destination_chat_id: int = 0,
    destination_thread_id: int | None = None,
    rule_item_ids: Sequence[int] = (),
    rule_selection_note: str | None = None,
) -> int:
    """Log a kick event and return its decision id.

    Proof is optional for a kick. When the moderator supplied it, the
    landed items are archived with the decision so the audit record points
    at the real media rather than only at a channel message.
    """
    now = utc_now()

    async def _work(sess: AsyncSession) -> int:
        case_id = await _open_case(sess, user_id, admin_id, reason, chat_id)
        upload_id = None
        if proof_items and destination_chat_id:
            upload_id = await moderation_db.archive_proof(
                sess,
                case_id,
                admin_id,
                0,
                destination_chat_id,
                items=proof_items,
                expected_item_count=proof_expected_count,
                destination_thread_id=destination_thread_id,
                is_required=False,
            )
        row = (
            (
                await sess.execute(
                    pg_insert(moderation_actions)
                    .values(
                        action_type="kick",
                        scope_type="chat",
                        chat_id=chat_id,
                        origin_chat_id=chat_id,
                        target_user_id=user_id,
                        actor_user_id=admin_id,
                        reason=reason,
                        created_at=now,
                        status="completed",
                        case_id=case_id,
                        evidence_upload_id=upload_id,
                        action_origin="manual",
                    )
                    .returning(moderation_actions.c.id)
                )
            )
            .mappings()
            .first()
        )
        if row is None:
            raise RuntimeError("the kick decision was not written")
        await moderation_db.link_case_rules(
            sess,
            case_id,
            rule_item_ids,
            admin_id,
            chat_id,
            rule_selection_note,
        )
        # * The investigation ends with its decision: an open case is
        # * picked up by the next decision about the same user, so the
        # * history would collapse into one case per user.
        await moderation_db.close_case(sess, case_id, admin_id)
        return int(row["id"])

    return await run_transaction(_work)


async def log_repair_kick(
    user_id: int, chat_id: int, actor_user_id: int, reason: str
) -> int:
    """Record a system-generated kick whose rejoin must be repaired.

    A fail-closed join removes a member by banning and immediately unbanning
    them. If the unban cannot land, the member stays removed without any
    history. This helper writes that history as a failed kick so the durable
    reconcile run can finish the rejoin and operators can see the attempt.
    The row starts ``completed`` because the insert guard requires that status
    for a kick, then moves to ``failed`` in the same transaction.
    """
    now = utc_now()

    async def _work(sess: AsyncSession) -> int:
        case_id = await _open_case(sess, user_id, actor_user_id, reason, chat_id)
        row = (
            (
                await sess.execute(
                    pg_insert(moderation_actions)
                    .values(
                        action_type="kick",
                        scope_type="chat",
                        chat_id=chat_id,
                        origin_chat_id=chat_id,
                        target_user_id=user_id,
                        actor_user_id=actor_user_id,
                        reason=reason,
                        created_at=now,
                        status="completed",
                        case_id=case_id,
                        action_origin="system",
                    )
                    .returning(moderation_actions.c.id)
                )
            )
            .mappings()
            .first()
        )
        if row is None:
            raise RuntimeError("the repair kick decision was not written")
        action_id = int(row["id"])
        await sess.execute(
            moderation_actions.update()
            .where(moderation_actions.c.id == action_id)
            .values(status="failed")
        )
        await moderation_db.close_case(sess, case_id, actor_user_id)
        return action_id

    return await run_transaction(_work)


async def mark_kick_failed(action_id: int) -> bool:
    """Record that a kick decision did not complete its ban or rejoin step.

    The audit row is written before enforcement so an applied kick can never
    be unaudited. The trade-off is that the row starts ``completed``; this
    update moves it to ``failed`` when the ban or its follow-up unban does
    not land, so the history does not report a kick that never happened.
    Returns True when the transition was applied.
    """
    if action_id <= 0:
        return False
    affected = await db_call(
        lambda: run(
            moderation_actions.update()
            .where(
                moderation_actions.c.id == action_id,
                moderation_actions.c.action_type == "kick",
                moderation_actions.c.status == "completed",
            )
            .values(status="failed")
        )
    )
    return affected > 0


async def mark_kick_completed(action_id: int) -> bool:
    """Close a failed kick once its durable unban repair lands."""
    if action_id <= 0:
        return False
    affected = await db_call(
        lambda: run(
            moderation_actions.update()
            .where(
                moderation_actions.c.id == action_id,
                moderation_actions.c.action_type == "kick",
                moderation_actions.c.status == "failed",
            )
            .values(status="completed")
        )
    )
    return affected > 0


async def _open_case(
    sess: AsyncSession, target_id: int, admin_id: int, reason: str, chat_id: int
) -> int:
    """Return the open case of the target, or open one for the decision."""
    return await moderation_db.open_case(
        sess,
        target_id,
        admin_id,
        title=f"Kick of {target_id} in group {chat_id}",
        summary=reason,
        severity="medium",
        requires_evidence=False,
    )


# ─────────────────────── Per-user history ───────────────────────── #


async def user_kicks(
    user_id: int, *, skip: int = 0, limit: int | None = None
) -> list[KickDoc]:
    """Return every kick record for a user, newest first.

    ``limit=None`` returns the full list (backwards compatible).
    """
    stmt = (
        select(*_KICK_COLUMNS)
        .where(
            moderation_actions.c.target_user_id == user_id,
            moderation_actions.c.action_type == "kick",
        )
        .order_by(
            moderation_actions.c.created_at.desc(),
            moderation_actions.c.id.desc(),
        )
        .offset(max(0, skip))
    )
    if limit is not None:
        stmt = stmt.limit(max(1, limit))
    rows = await db_call(lambda: fetch_all(stmt))
    return [
        KickDoc(
            target_user_id=UserId(int(row["target_user_id"])),
            chat_id=ChatId(int(row["chat_id"])),
            reason=str(row["reason"]),
            actor_user_id=UserId(int(row["actor_user_id"])),
            timestamp=cast("datetime", row["created_at"]),
            status=cast("ActionStatus", row["status"]),
        )
        for row in rows
    ]


async def user_kick_count(user_id: int) -> int:
    """Count every kick ever logged against the user."""
    total = await db_call(
        lambda: fetch_value(
            select(func.count())
            .select_from(moderation_actions)
            .where(
                moderation_actions.c.target_user_id == user_id,
                moderation_actions.c.action_type == "kick",
            )
        )
    )
    return int(total or 0)


# ───────────────────────────── Migration ─────────────────────────── #
# * The community schema moves a group as one transaction, so the
# * decisions of a group follow it through
# * :func:`tcbot.database.groups_db.migrate_group`.
