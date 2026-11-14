# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Claim and record the queued enforcement runs of expired decisions."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from sqlalchemy import text

from tcbot.database.engine import run_transaction
from tcbot.utils.time_and_date import utc_now

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

_RUN_CLAIM = text(
    """
    WITH picked AS (
        SELECT id
          FROM moderation_enforcement_runs
         WHERE status = 'queued'
           AND operation = 'revoke'
         ORDER BY created_at
         FOR UPDATE SKIP LOCKED
         LIMIT :limit
    )
    UPDATE moderation_enforcement_runs AS r
       SET status = 'running',
           started_at = COALESCE(r.started_at, now()),
           updated_at = now()
      FROM picked
     WHERE r.id = picked.id
    RETURNING r.id, r.action_id, r.operation
    """
)

_REQUEUE_RUNS = text(
    """
    UPDATE moderation_enforcement_runs
       SET status = 'queued', updated_at = now()
     WHERE status = 'running'
       AND updated_at < now() - make_interval(secs => :stale_seconds)
    RETURNING id
    """
)

_REQUEUE_TARGETS = text(
    """
    UPDATE moderation_enforcement_targets AS t
       SET status = 'pending', updated_at = now()
      FROM moderation_enforcement_runs AS r
     WHERE t.run_id = r.id
       AND r.status = 'queued'
       AND t.status = 'in_progress'
    """
)

_RUN_ACTION = text(
    """
    SELECT a.target_user_id,
           a.action_type,
           a.status AS action_status,
           r.operation
      FROM moderation_enforcement_runs AS r
      JOIN moderation_actions AS a ON a.id = r.action_id
     WHERE r.id = :run_id
    """
)

_TARGET_CLAIM = text(
    """
    WITH picked AS (
        SELECT id
          FROM moderation_enforcement_targets
         WHERE run_id = :run_id
           AND (
               status = 'pending'
               OR (status = 'failed' AND next_retry_at IS NOT NULL
                   AND next_retry_at <= now())
           )
         ORDER BY id
         FOR UPDATE SKIP LOCKED
         LIMIT :limit
    )
    UPDATE moderation_enforcement_targets AS t
       SET status = 'in_progress', updated_at = now()
      FROM picked
     WHERE t.id = picked.id
    RETURNING t.id, t.chat_id, t.attempt_count
    """
)

_TARGET_LOCK = text(
    """
    SELECT attempt_count
      FROM moderation_enforcement_targets
     WHERE id = :target_id
       FOR UPDATE
    """
)

# * The attempt guard requires the target to still be in_progress with the
# * attempt number being inserted, so the attempt lands before the status
# * move.
_ATTEMPT_INSERT = text(
    """
    INSERT INTO moderation_enforcement_attempts (
        target_id, attempt_number, outcome, error_kind, error_code, error_detail
    )
    VALUES (
        :target_id, :attempt_number, :outcome, :error_kind, :error_code,
        :error_detail
    )
    """
)

_TARGET_UPDATE = text(
    """
    UPDATE moderation_enforcement_targets
       SET status = :status,
           first_attempt_at = COALESCE(first_attempt_at, now()),
           last_attempt_at = now(),
           completed_at = CASE WHEN :status IN ('succeeded', 'skipped', 'failed')
                               THEN now() ELSE NULL END,
           last_error_kind = :error_kind,
           last_error_code = :error_code,
           last_error_detail = :error_detail,
           next_retry_at = :next_retry_at,
           updated_at = now()
     WHERE id = :target_id
    """
)

_COMPLETE_EMPTY_RUN = text(
    """
    UPDATE moderation_enforcement_runs
       SET status = 'completed', finished_at = now(), updated_at = now()
     WHERE id = :run_id
       AND NOT EXISTS (
           SELECT 1 FROM moderation_enforcement_targets WHERE run_id = :run_id
       )
    """
)

_CANCEL_RUN = text(
    """
    UPDATE moderation_enforcement_runs
       SET status = 'cancelled', finished_at = now(), updated_at = now()
     WHERE id = :run_id AND status = 'running'
    """
)


async def claim_runs(limit: int = 10) -> list[dict[str, object]]:
    """Claim queued enforcement runs for one worker."""

    async def _work(sess: AsyncSession) -> list[dict[str, object]]:
        result = await sess.execute(_RUN_CLAIM, {"limit": limit})
        return [dict(row) for row in result.mappings()]

    return await run_transaction(_work)


async def requeue_stale_runs(stale_after: timedelta = timedelta(minutes=30)) -> None:
    """Return runs abandoned by a crashed worker to the queue."""

    async def _work(sess: AsyncSession) -> None:
        await sess.execute(
            _REQUEUE_RUNS, {"stale_seconds": int(stale_after.total_seconds())}
        )
        await sess.execute(_REQUEUE_TARGETS)

    await run_transaction(_work)


async def load_run_action(run_id: int) -> dict[str, object] | None:
    """Return the action a claimed run belongs to."""

    async def _work(sess: AsyncSession) -> dict[str, object] | None:
        result = await sess.execute(_RUN_ACTION, {"run_id": run_id})
        row = result.mappings().first()
        return dict(row) if row is not None else None

    return await run_transaction(_work)


async def claim_targets(run_id: int, limit: int = 100) -> list[dict[str, object]]:
    """Claim the pending targets of one run."""

    async def _work(sess: AsyncSession) -> list[dict[str, object]]:
        result = await sess.execute(_TARGET_CLAIM, {"run_id": run_id, "limit": limit})
        return [dict(row) for row in result.mappings()]

    return await run_transaction(_work)


async def complete_target(
    target_id: int,
    *,
    status: str,
    outcome: str,
    error_kind: str | None = None,
    error_code: str | None = None,
    error_detail: str | None = None,
    retry_after: timedelta | None = None,
) -> None:
    """Record one target outcome, its attempt row, and any retry deadline."""
    if status not in ("pending", "succeeded", "skipped", "failed"):
        raise ValueError(f"Refusing unknown enforcement target status {status!r}")
    if outcome not in ("succeeded", "skipped", "failed"):
        raise ValueError(f"Refusing unknown enforcement outcome {outcome!r}")
    next_retry_at = utc_now() + retry_after if retry_after is not None else None

    async def _work(sess: AsyncSession) -> None:
        attempt_number = await sess.scalar(_TARGET_LOCK, {"target_id": target_id})
        if attempt_number is None:
            return
        await sess.execute(
            _ATTEMPT_INSERT,
            {
                "target_id": target_id,
                "attempt_number": int(attempt_number),
                "outcome": outcome,
                "error_kind": error_kind,
                "error_code": error_code,
                "error_detail": error_detail,
            },
        )
        await sess.execute(
            _TARGET_UPDATE,
            {
                "target_id": target_id,
                "status": status,
                "error_kind": error_kind,
                "error_code": error_code,
                "error_detail": error_detail,
                "next_retry_at": next_retry_at,
            },
        )

    await run_transaction(_work)


async def complete_empty_run(run_id: int) -> None:
    """Close a run that has no target to enforce."""

    async def _work(sess: AsyncSession) -> None:
        await sess.execute(_COMPLETE_EMPTY_RUN, {"run_id": run_id})

    await run_transaction(_work)


async def cancel_run(run_id: int, *, error_detail: str) -> None:
    """Cancel a run whose action is no longer expirable."""
    _ = error_detail

    async def _work(sess: AsyncSession) -> None:
        await sess.execute(_CANCEL_RUN, {"run_id": run_id})

    await run_transaction(_work)
