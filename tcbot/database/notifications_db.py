# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Durable review-card edits whose direct Telegram update failed."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from tcbot.database.base import moderation_notification_tasks
from tcbot.database.engine import run_transaction
from tcbot.utils.logger import get_logger
from tcbot.utils.time_and_date import utc_now

if TYPE_CHECKING:
    from datetime import timedelta

    from sqlalchemy.ext.asyncio import AsyncSession

log = get_logger(__name__)

_CLAIM_DUE = text(
    """
    WITH picked AS (
        SELECT id
          FROM moderation_notification_tasks
         WHERE state = 'pending'
           AND (next_retry_at IS NULL OR next_retry_at <= now())
         ORDER BY id
         FOR UPDATE SKIP LOCKED
         LIMIT :limit
    )
    UPDATE moderation_notification_tasks AS t
       SET attempts = t.attempts + 1,
           next_retry_at = now() + make_interval(secs => :retry_seconds),
           updated_at = now()
      FROM picked
     WHERE t.id = picked.id
    RETURNING t.id, t.action_id, t.chat_id, t.message_id, t.attempts
    """
)

_TASK_ACTION = text(
    """
    SELECT a.external_ref,
           a.target_user_id,
           a.status,
           a.metadata->>'review_message_id' AS review_message_id,
           EXISTS (
               SELECT 1
                 FROM moderation_appeals AS ap
                WHERE ap.action_id = a.id
                  AND ap.status = 'pending'
           ) AS has_pending_appeal
      FROM moderation_notification_tasks AS t
      JOIN moderation_actions AS a ON a.id = t.action_id
     WHERE t.id = :task_id
    """
)


async def queue_review_card_edit(
    sess: AsyncSession, action_id: int, chat_id: int, message_id: int
) -> None:
    """Queue one review-card edit inside the caller's transaction."""
    if action_id <= 0 or chat_id == 0 or message_id <= 0:
        return
    await sess.execute(
        pg_insert(moderation_notification_tasks)
        .values(
            action_id=action_id,
            chat_id=chat_id,
            message_id=message_id,
            kind="review_card",
            state="pending",
            attempts=0,
            next_retry_at=None,
            last_error=None,
        )
        .on_conflict_do_update(
            constraint="uq_moderation_notification_action_kind",
            set_={
                "chat_id": chat_id,
                "message_id": message_id,
                "state": "pending",
                "attempts": 0,
                "next_retry_at": None,
                "last_error": None,
                "updated_at": utc_now(),
            },
        )
    )


async def enqueue_review_card_edit(
    action_id: int, chat_id: int, message_id: int
) -> None:
    """Queue a card edit in its own transaction; failures are logged."""
    if action_id <= 0 or chat_id == 0 or message_id <= 0:
        return
    try:
        await run_transaction(
            lambda sess: queue_review_card_edit(sess, action_id, chat_id, message_id)
        )
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception(
            "Review-card outbox write failed for action=%d message=%d",
            action_id,
            message_id,
        )


async def claim_due_tasks(
    limit: int = 10, *, retry_after: timedelta
) -> list[dict[str, object]]:
    """Claim due card edits and reserve their next retry window."""

    async def _work(sess: AsyncSession) -> list[dict[str, object]]:
        result = await sess.execute(
            _CLAIM_DUE,
            {
                "limit": limit,
                "retry_seconds": max(1, int(retry_after.total_seconds())),
            },
        )
        return [dict(row) for row in result.mappings()]

    return await run_transaction(_work)


async def load_task_action(task_id: int) -> dict[str, object] | None:
    """Return the decision a card-edit task belongs to."""

    async def _work(sess: AsyncSession) -> dict[str, object] | None:
        row = (
            (await sess.execute(_TASK_ACTION, {"task_id": task_id})).mappings().first()
        )
        return dict(row) if row is not None else None

    return await run_transaction(_work)


async def complete_task(
    task_id: int,
    *,
    state: str,
    error: str | None = None,
    retry_after: timedelta | None = None,
    expected_attempts: int | None = None,
    expected_message_id: int | None = None,
) -> None:
    """Mark one card-edit task terminal or schedule its next retry.

    A worker passes the attempt count and card message id it observed. The
    update applies only while both still match the pending row, so a
    re-queued task with a newer card cannot be completed by the previous
    worker even when the attempt counter wrapped back to the same value.
    """
    if state not in ("pending", "sent", "failed", "skipped"):
        raise ValueError(f"Refusing unknown notification state {state!r}")
    next_retry_at = utc_now() + retry_after if retry_after is not None else None
    stmt = moderation_notification_tasks.update().where(
        moderation_notification_tasks.c.id == task_id
    )
    if expected_attempts is not None:
        stmt = stmt.where(
            moderation_notification_tasks.c.state == "pending",
            moderation_notification_tasks.c.attempts == expected_attempts,
        )
    if expected_message_id is not None:
        stmt = stmt.where(
            moderation_notification_tasks.c.message_id == expected_message_id
        )
    await run_transaction(
        lambda sess: sess.execute(
            stmt.values(
                state=state,
                last_error=error,
                next_retry_at=next_retry_at,
                updated_at=utc_now(),
            )
        )
    )
