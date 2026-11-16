# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Terminal ban transitions: revoke and appeal approval with their delivery."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from sqlalchemy import select

from tcbot.database import enforcement_db, notifications_db
from tcbot.database.base import moderation_actions, moderation_appeals
from tcbot.database.engine import run_transaction
from tcbot.database.users_cache import ensure_users
from tcbot.utils.time_and_date import utc_now

from ._shared import _drop_review_keys, _in_force

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.engine import CursorResult
    from sqlalchemy.ext.asyncio import AsyncSession


async def revoke_ban_and_queue_unban(
    user_id: int,
    requested_by_user_id: int | None,
    chat_ids: Sequence[int],
    *,
    review_chat_id: int | None = None,
    review_message_id: int | None = None,
) -> tuple[int, int | None]:
    """Revoke the active ban and queue its unban delivery in one transaction.

    The revocation is the domain decision; the run is the durable work
    item. They have to land together: a revoked record without a run loses
    the groups that failed the fan-out, and a run without a revoked record
    is cancelled by the worker. Pending appeals are withdrawn in the same
    transaction, and the review slot is released so a stale card cannot
    promise a decision that is already gone. A review card outside this
    transaction is queued here as well, so a crash after the commit cannot
    leave a live-looking card over a revoked decision.
    """

    async def _work(sess: AsyncSession) -> tuple[int, int | None]:
        action_ids = list(
            (
                await sess.scalars(
                    select(moderation_actions.c.id)
                    .where(
                        moderation_actions.c.target_user_id == user_id,
                        moderation_actions.c.action_type == "ban",
                        moderation_actions.c.status == "active",
                    )
                    .with_for_update()
                )
            ).all()
        )
        if not action_ids:
            return 0, None
        # * The run references the acting staff member. An account the
        # * member cache has never seen must not fail the unban on a
        # * foreign key, so the identity row joins this transaction.
        await ensure_users(sess, requested_by_user_id or 0)
        await sess.execute(
            moderation_appeals.update()
            .where(
                moderation_appeals.c.action_id.in_(action_ids),
                moderation_appeals.c.status == "pending",
            )
            .values(
                status="withdrawn",
                resolved_at=utc_now(),
                decision_note="Ban lifted by staff",
            )
        )
        result = await sess.execute(
            moderation_actions.update()
            .where(
                moderation_actions.c.id.in_(action_ids),
                moderation_actions.c.status == "active",
            )
            .values(
                status="revoked",
                revoked_at=utc_now(),
                metadata=_drop_review_keys(),
            )
        )
        revoked = cast("CursorResult", result).rowcount
        run_id: int | None = None
        for action_id in action_ids:
            queued = await enforcement_db.queue_run(
                sess,
                action_id=int(action_id),
                operation="revoke",
                idempotency_key=f"moderation:{action_id}:revoke:manual:v1",
                requested_by_user_id=requested_by_user_id,
                chat_ids=chat_ids,
            )
            run_id = run_id or queued
        if review_chat_id and review_message_id:
            await notifications_db.queue_review_card_edit(
                sess, int(action_ids[0]), review_chat_id, review_message_id
            )
        return revoked, run_id

    return await run_transaction(_work)


async def approve_appeal_and_queue_unban(
    ban_id: str,
    reviewer_id: int,
    reviewer_name: str,
    requested_by_user_id: int | None,
    chat_ids: Sequence[int],
) -> tuple[bool, int | None]:
    """Accept the pending appeal, revoke its ban, and queue the unban.

    The appeal status, the ban status, the review slot, and the delivery
    run are one transaction. A former split let the ban lift while the
    appeal stayed pending, so /check and the review card disagreed about
    the decision the staff member had just made.
    """

    async def _work(sess: AsyncSession) -> tuple[bool, int | None]:
        action_id = await sess.scalar(
            select(moderation_actions.c.id)
            .where(
                moderation_actions.c.external_ref == ban_id,
                moderation_actions.c.action_type == "ban",
                moderation_actions.c.status == "active",
                # * A timed ban whose deadline passed is no longer in force,
                # * even before the daily sweep moves the row. Accepting the
                # * appeal would record a staff decision about a restriction
                # * nobody can enforce.
                _in_force(),
            )
            .with_for_update()
        )
        if action_id is None:
            return False, None
        await ensure_users(sess, requested_by_user_id or 0, reviewer_id)
        accepted = await sess.execute(
            moderation_appeals.update()
            .where(
                moderation_appeals.c.action_id == action_id,
                moderation_appeals.c.status == "pending",
            )
            .values(
                status="accepted",
                resolved_at=utc_now(),
                reviewed_by_user_id=reviewer_id,
                decision_note=reviewer_name,
            )
        )
        if cast("CursorResult", accepted).rowcount == 0:
            return False, None
        revoked = await sess.execute(
            moderation_actions.update()
            .where(
                moderation_actions.c.id == action_id,
                moderation_actions.c.status == "active",
            )
            .values(
                status="revoked",
                revoked_at=utc_now(),
                metadata=_drop_review_keys(),
            )
        )
        if cast("CursorResult", revoked).rowcount == 0:
            # * The appeal acceptance already ran in this transaction, so
            # * the whole unit has to roll back instead of committing an
            # * accepted appeal that still sits on an active ban.
            raise RuntimeError(f"the ban {ban_id!r} could not be revoked")
        run_id = await enforcement_db.queue_run(
            sess,
            action_id=int(action_id),
            operation="revoke",
            idempotency_key=f"moderation:{action_id}:revoke:appeal:v1",
            requested_by_user_id=requested_by_user_id,
            chat_ids=chat_ids,
        )
        return True, run_id

    return await run_transaction(_work)


async def reject_appeal(ban_id: str, reviewer_id: int, reviewer_name: str) -> bool:
    """Reject the pending appeal and release its review slot in one transaction.

    The rejection is the decision and the slot release is part of it. A
    split write could record the rejection while the card still holds the
    slot, so the next tap finds a decided appeal and the decision cannot be
    appealed again until the stale window passes.
    """

    async def _work(sess: AsyncSession) -> bool:
        action_id = await sess.scalar(
            select(moderation_actions.c.id)
            .where(
                moderation_actions.c.external_ref == ban_id,
                moderation_actions.c.action_type == "ban",
            )
            .with_for_update()
        )
        if action_id is None:
            return False
        await ensure_users(sess, reviewer_id)
        rejected = await sess.execute(
            moderation_appeals.update()
            .where(
                moderation_appeals.c.action_id == action_id,
                moderation_appeals.c.status == "pending",
            )
            .values(
                status="rejected",
                resolved_at=utc_now(),
                reviewed_by_user_id=reviewer_id,
                decision_note=reviewer_name,
            )
        )
        if cast("CursorResult", rejected).rowcount == 0:
            return False
        await sess.execute(
            moderation_actions.update()
            .where(moderation_actions.c.id == action_id)
            .values(metadata=_drop_review_keys())
        )
        return True

    return await run_transaction(_work)
