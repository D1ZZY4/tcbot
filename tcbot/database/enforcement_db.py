# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Queue, claim, report, and requeue the enforcement runs of decisions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Literal

from sqlalchemy import text

from tcbot.database.engine import run_transaction
from tcbot.utils.time_and_date import utc_now

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.ext.asyncio import AsyncSession

_RUN_CLAIM = text(
    """
    WITH picked AS (
        SELECT id
          FROM moderation_enforcement_runs
         WHERE status = 'queued'
           AND operation IN ('apply', 'revoke', 'reconcile')
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

_CLAIM_ONE_RUN = text(
    """
    UPDATE moderation_enforcement_runs
       SET status = 'running',
           started_at = COALESCE(started_at, now()),
           updated_at = now()
     WHERE id = :run_id AND status = 'queued'
    RETURNING id, action_id, operation
    """
)

_REQUEUE_RUNS = text(
    """
    UPDATE moderation_enforcement_runs AS r
       SET status = 'queued', updated_at = now()
     WHERE (
               r.status = 'running'
               AND r.updated_at < now() - make_interval(secs => :stale_seconds)
           )
        OR (
               r.status IN ('failed', 'partial', 'completed')
               AND EXISTS (
                   SELECT 1
                     FROM moderation_enforcement_targets AS t
                     JOIN connected_chats AS cc ON cc.chat_id = t.chat_id
                    WHERE t.run_id = r.id
                      AND t.status = 'failed'
                      AND t.next_retry_at IS NOT NULL
                      AND t.next_retry_at <= now()
                      AND cc.is_active
               )
           )
    RETURNING r.id
    """
)

# * A target of an abandoned run is released as failed with a due retry
# * deadline, never as pending: the target trigger only accepts
# * in_progress -> succeeded|skipped|failed. The run is re-queued below, so
# * the next tick claims the due target through the failed-retry branch.
_REQUEUE_TARGETS = text(
    """
    UPDATE moderation_enforcement_targets AS t
       SET status = 'failed',
           next_retry_at = now(),
           last_error_kind = 'worker_timeout',
           last_error_detail = 'Target stayed in progress past the stale-run window and was released for retry',
           updated_at = now()
      FROM moderation_enforcement_runs AS r
     WHERE t.run_id = r.id
       AND r.status = 'running'
       AND r.updated_at < now() - make_interval(secs => :stale_seconds)
       AND t.status = 'in_progress'
    """
)

_RUN_ACTION = text(
    """
    SELECT a.id AS action_id,
           a.target_user_id,
           a.action_type,
           a.status AS action_status,
           a.expires_at,
           r.operation,
           EXISTS (
               SELECT 1
                 FROM moderation_actions AS n
                WHERE n.target_user_id = a.target_user_id
                  AND n.action_type = a.action_type
                  AND n.status = 'active'
                  AND n.id > a.id
           ) AS newer_active,
           EXISTS (
               SELECT 1
                 FROM moderation_actions AS b
                WHERE b.target_user_id = a.target_user_id
                  AND b.action_type = 'ban'
                  AND b.status = 'active'
           ) AS active_ban
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
                   AND next_retry_at <= now()
                   AND EXISTS (
                       SELECT 1
                         FROM connected_chats AS cc
                        WHERE cc.chat_id = moderation_enforcement_targets.chat_id
                          AND cc.is_active
                   ))
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
       SET status = 'cancelled',
           finished_at = now(),
           updated_at = now(),
           metadata = metadata || jsonb_build_object(
               'cancel_reason', CAST(:error_detail AS text)
           )
     WHERE id = :run_id AND status = 'running'
    """
)

_QUEUE_RUN = text(
    """
    INSERT INTO moderation_enforcement_runs (
        action_id, operation, idempotency_key, requested_by_user_id, status
    )
    VALUES (:action_id, :operation, :idempotency_key, :requested_by_user_id, 'queued')
    ON CONFLICT (idempotency_key) DO NOTHING
    RETURNING id
    """
)

_RUN_BY_KEY = text(
    """
    SELECT id FROM moderation_enforcement_runs WHERE idempotency_key = :idempotency_key
    """
)

_QUEUE_TARGETS = text(
    """
    INSERT INTO moderation_enforcement_targets (run_id, chat_id)
    SELECT :run_id, cc.chat_id
      FROM connected_chats AS cc
     WHERE cc.chat_id = ANY(:chat_ids)
       AND cc.is_active
    ON CONFLICT (run_id, chat_id) DO NOTHING
    """
)

_RUN_REPORT = text(
    """
    SELECT r.id, r.action_id, r.operation, r.status, r.target_count,
           r.succeeded_count, r.failed_count, r.skipped_count,
           r.started_at, r.finished_at
      FROM moderation_enforcement_runs AS r
     WHERE r.id = :run_id
    """
)

_TARGET_REPORT = text(
    """
    SELECT t.id, t.chat_id, t.status, t.attempt_count, t.last_error_kind,
           t.last_error_detail, t.next_retry_at, tc.title
      FROM moderation_enforcement_targets AS t
      LEFT JOIN telegram_chats AS tc ON tc.chat_id = t.chat_id
     WHERE t.run_id = :run_id
     ORDER BY t.id
    """
)

_KICK_ACTION_EXISTS = text(
    """
    SELECT 1
      FROM moderation_actions
     WHERE id = :action_id
       AND action_type = 'kick'
       AND scope_type = 'chat'
       AND chat_id = :chat_id
    """
)

_CONNECT_REPLAY_ACTIONS = text(
    """
    SELECT id, target_user_id, action_type
      FROM moderation_actions
     WHERE status = 'active'
       AND action_type IN ('ban', 'mute')
       AND target_user_id = ANY(:user_ids)
    """
)

# * The operator view of the ledger: only the runs a person may still have to
# * act on. A completed run is absent even when it is recent, because the
# * delivery already landed and there is nothing to repair.
_UNSETTLED_RUNS = text(
    """
    SELECT r.id, r.action_id, r.operation, r.status, r.target_count,
           r.succeeded_count, r.failed_count, r.skipped_count,
           a.action_type, a.target_user_id, a.status AS action_status,
           r.created_at, r.updated_at,
           count(t.id) FILTER (WHERE t.status = 'failed') AS failed_targets,
           count(t.id) FILTER (
               WHERE t.status = 'failed' AND t.next_retry_at IS NULL
           ) AS exhausted_targets
      FROM moderation_enforcement_runs AS r
      JOIN moderation_actions AS a ON a.id = r.action_id
      LEFT JOIN moderation_enforcement_targets AS t ON t.run_id = r.id
     WHERE r.status IN ('queued', 'running', 'partial', 'failed')
     GROUP BY r.id, a.action_type, a.target_user_id, a.status
     ORDER BY r.updated_at DESC, r.id DESC
     LIMIT :limit
    """
)

_REDRIVE_RUN_LOCK = text(
    """
    SELECT status
      FROM moderation_enforcement_runs
     WHERE id = :run_id
       FOR UPDATE
    """
)

# * A manual replay only brings the retry deadline forward. The target
# * trigger accepts failed -> failed when next_retry_at changes, and the
# * attempt history keeps what actually happened.
_REDRIVE_TARGETS = text(
    """
    UPDATE moderation_enforcement_targets
       SET next_retry_at = now(),
           updated_at = now()
     WHERE run_id = :run_id
       AND status = 'failed'
       AND (CAST(:chat_id AS bigint) IS NULL OR chat_id = :chat_id)
    RETURNING id
    """
)

_REDRIVE_RUN = text(
    """
    UPDATE moderation_enforcement_runs
       SET status = 'queued',
           finished_at = NULL,
           updated_at = now()
     WHERE id = :run_id
    """
)


async def claim_runs(limit: int = 10) -> list[dict[str, object]]:
    """Claim queued enforcement runs for one worker."""

    async def _work(sess: AsyncSession) -> list[dict[str, object]]:
        result = await sess.execute(_RUN_CLAIM, {"limit": limit})
        return [dict(row) for row in result.mappings()]

    return await run_transaction(_work)


async def claim_run(run_id: int) -> dict[str, object] | None:
    """Claim one specific queued run for immediate delivery."""

    async def _work(sess: AsyncSession) -> dict[str, object] | None:
        result = await sess.execute(_CLAIM_ONE_RUN, {"run_id": run_id})
        row = result.mappings().first()
        return dict(row) if row is not None else None

    return await run_transaction(_work)


async def queue_run(
    sess: AsyncSession,
    *,
    action_id: int,
    operation: str,
    idempotency_key: str,
    requested_by_user_id: int | None,
    chat_ids: Sequence[int],
) -> int:
    """Queue one enforcement run and its targets inside the caller's transaction."""
    result = await sess.execute(
        _QUEUE_RUN,
        {
            "action_id": action_id,
            "operation": operation,
            "idempotency_key": idempotency_key,
            "requested_by_user_id": requested_by_user_id,
        },
    )
    row = result.first()
    run_id = int(row[0]) if row is not None else None
    if run_id is None:
        run_id = await sess.scalar(_RUN_BY_KEY, {"idempotency_key": idempotency_key})
    if run_id is None:
        raise RuntimeError(f"the enforcement run {idempotency_key!r} was not written")
    targets = [chat_id for chat_id in dict.fromkeys(chat_ids) if chat_id]
    if targets:
        await sess.execute(_QUEUE_TARGETS, {"run_id": int(run_id), "chat_ids": targets})
    return int(run_id)


async def queue_kick_unban_repair(
    action_id: int, chat_id: int, requested_by_user_id: int | None
) -> int | None:
    """Queue a durable unban for a kick whose second step failed.

    The kick decision is marked ``failed`` because the rejoin did not land.
    The reconcile run is the repair task: the worker unbans the one chat,
    keeps retrying until Telegram accepts it, and moves the record back to
    ``completed`` only when the repair succeeds.
    """
    if action_id <= 0 or chat_id == 0:
        return None

    async def _work(sess: AsyncSession) -> int | None:
        exists = await sess.scalar(
            _KICK_ACTION_EXISTS, {"action_id": action_id, "chat_id": chat_id}
        )
        if exists is None:
            return None
        return await queue_run(
            sess,
            action_id=action_id,
            operation="reconcile",
            idempotency_key=f"moderation:{action_id}:kick-unban:v1",
            requested_by_user_id=requested_by_user_id,
            chat_ids=(chat_id,),
        )

    return await run_transaction(_work)


async def queue_connect_replay(
    chat_id: int,
    user_ids: Sequence[int],
    requested_by_user_id: int | None,
) -> int:
    """Queue one apply run per active ban or mute for a newly connected group.

    The connect replay is bounded by a time budget and a list cap, so a
    large federation can leave part of the list unenforced. The remainder
    becomes durable work here instead of disappearing with the connect
    handler: the worker retries each decision against the one new chat.
    Returns the number of queued decisions.
    """
    targets = [user_id for user_id in dict.fromkeys(user_ids) if user_id > 0]
    if chat_id == 0 or not targets:
        return 0

    async def _work(sess: AsyncSession) -> int:
        rows = (
            (await sess.execute(_CONNECT_REPLAY_ACTIONS, {"user_ids": targets}))
            .mappings()
            .all()
        )
        event = utc_now().strftime("%Y%m%dT%H%M%S")
        queued = 0
        for row in rows:
            action_id = int(row["id"])
            action_type = str(row["action_type"])
            await queue_run(
                sess,
                action_id=action_id,
                operation="apply",
                idempotency_key=(
                    f"moderation:{action_id}:connect-replay:"
                    f"{chat_id}:{event}:{action_type}:v1"
                ),
                requested_by_user_id=requested_by_user_id,
                chat_ids=(chat_id,),
            )
            queued += 1
        return queued

    return await run_transaction(_work)


async def run_report(run_id: int) -> dict[str, object] | None:
    """Return one run with its per-group targets for an operator summary."""

    async def _work(sess: AsyncSession) -> dict[str, object] | None:
        run_row = (
            (await sess.execute(_RUN_REPORT, {"run_id": run_id})).mappings().first()
        )
        if run_row is None:
            return None
        target_rows = (
            (await sess.execute(_TARGET_REPORT, {"run_id": run_id})).mappings().all()
        )
        report = dict(run_row)
        report["targets"] = [dict(row) for row in target_rows]
        return report

    return await run_transaction(_work)


async def list_unsettled_runs(limit: int = 10) -> list[dict[str, object]]:
    """Return the runs an operator may still have to repair.

    A run is unsettled while it is queued, running, partial, or failed.
    The rows carry the counters of the run plus the number of failed
    targets and the number of those whose retry budget is exhausted, so
    the operator view can separate "the worker will retry this" from
    "nothing will move until a person re-drives it".

    The limit is clamped: the command renders the rows in one message, and
    an unbounded read would let a backlog grow the reply without bound.
    """

    async def _work(sess: AsyncSession) -> list[dict[str, object]]:
        rows = (
            (await sess.execute(_UNSETTLED_RUNS, {"limit": max(1, min(limit, 50))}))
            .mappings()
            .all()
        )
        return [dict(row) for row in rows]

    return await run_transaction(_work)


async def redrive_run(run_id: int, *, chat_id: int | None = None) -> RepairResult:
    """Bring the failed targets of one run forward for another attempt.

    The repair keeps the original decision and run: a new moderation
    action would be a new verdict, while the operator only wants the
    delivery of the existing one. A run that a worker still owns is left
    alone, and a cancelled run is terminal. When *chat_id* is given, only
    that one group is re-driven.
    """

    async def _work(sess: AsyncSession) -> RepairResult:
        status = await sess.scalar(_REDRIVE_RUN_LOCK, {"run_id": run_id})
        if status is None:
            return RepairResult("missing")
        if status == "cancelled":
            return RepairResult("cancelled")
        if status in ("queued", "running"):
            return RepairResult("in_progress")
        rows = (
            (
                await sess.execute(
                    _REDRIVE_TARGETS, {"run_id": run_id, "chat_id": chat_id}
                )
            )
            .mappings()
            .all()
        )
        if not rows:
            return RepairResult("no_failed_target")
        await sess.execute(_REDRIVE_RUN, {"run_id": run_id})
        return RepairResult("queued", len(rows))

    return await run_transaction(_work)


def report_count(report: dict[str, object] | None, key: str, default: int = 0) -> int:
    """Read one integer counter from a run report."""
    value = (report or {}).get(key)
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return 0
    return default


def report_targets(report: dict[str, object] | None) -> list[dict[str, object]]:
    """Return the target rows of a run report."""
    raw = (report or {}).get("targets")
    if not isinstance(raw, list):
        return []
    return [row for row in raw if isinstance(row, dict)]


def failed_report_targets(
    report: dict[str, object] | None,
) -> list[dict[str, object]]:
    """Return the targets whose delivery ended in failure."""
    return [
        target
        for target in report_targets(report)
        if str(target.get("status")) == "failed"
    ]


def landed_report_chat_ids(report: dict[str, object] | None) -> list[int]:
    """Return the chats where the run did not fail."""
    landed: list[int] = []
    for target in report_targets(report):
        if str(target.get("status")) not in ("succeeded", "skipped"):
            continue
        chat_id = target.get("chat_id")
        if isinstance(chat_id, int):
            landed.append(chat_id)
    return landed


def report_landed_count(report: dict[str, object] | None) -> int:
    """Return the targets Telegram accepted or had nothing to do for."""
    return report_count(report, "succeeded_count") + report_count(
        report, "skipped_count"
    )


RepairState = Literal[
    "queued",
    "no_failed_target",
    "in_progress",
    "cancelled",
    "missing",
]


@dataclass(frozen=True)
class RepairResult:
    """The outcome of one operator re-drive request."""

    state: RepairState
    targets: int = 0


@dataclass(frozen=True)
class DeliveryOutcome:
    """The per-group delivery counts of one enforcement run."""

    total: int
    applied: int
    failed: int
    pending: int


def delivery_outcome(
    report: dict[str, object] | None, fallback_total: int = 0
) -> DeliveryOutcome:
    """Summarise a run from its targets, falling back to its counters.

    The target rows are the authoritative per-group results, so they win
    when present. The run counters and the caller's group count are only a
    fallback for a report that could not be read: the answer then reports
    every group as pending instead of claiming a delivery nobody observed.
    """
    targets = report_targets(report)
    if targets:
        statuses = [str(target.get("status") or "") for target in targets]
        return DeliveryOutcome(
            total=len(statuses),
            applied=sum(status in ("succeeded", "skipped") for status in statuses),
            failed=sum(status == "failed" for status in statuses),
            pending=sum(status in ("pending", "in_progress") for status in statuses),
        )
    total = report_count(report, "target_count") or fallback_total
    applied = report_landed_count(report)
    failed = report_count(report, "failed_count")
    return DeliveryOutcome(
        total=total,
        applied=applied,
        failed=failed,
        pending=max(0, total - applied - failed),
    )


def report_settled(report: dict[str, object] | None) -> bool:
    """Return True when a run reached a terminal delivery status.

    ``failed`` and ``partial`` are terminal for the current attempt: a
    target that still has a retry deadline reopens the run as ``queued``
    through the requeue pass, so those two states only describe a run with
    no in-flight target. A report without a run status is settled only when
    every target row it carries is terminal.
    """
    if report is None:
        return False
    if str(report.get("status") or "") in (
        "completed",
        "partial",
        "failed",
        "cancelled",
    ):
        return True
    targets = report_targets(report)
    return bool(targets) and all(
        str(target.get("status") or "") in ("succeeded", "skipped", "failed")
        for target in targets
    )


async def requeue_stale_runs(stale_after: timedelta = timedelta(minutes=30)) -> None:
    """Return abandoned runs and their in-flight targets to the queue.

    The target release runs first: it moves a stranded ``in_progress``
    target to ``failed`` with a due retry deadline (the only transition the
    target trigger accepts), and the run refresh trigger may then close the
    run. The run statement re-queues both the stale runs and any run that
    holds a due retry, so the next tick claims the target again.
    """

    async def _work(sess: AsyncSession) -> None:
        params = {"stale_seconds": int(stale_after.total_seconds())}
        await sess.execute(_REQUEUE_TARGETS, params)
        await sess.execute(_REQUEUE_RUNS, params)

    await run_transaction(_work)


async def load_run_action(run_id: int) -> dict[str, object] | None:
    """Return the action of a claimed run, with its conflicting decisions.

    ``newer_active`` is true when a later decision of the same type and
    target is in force; a revoke run must not lift a restriction that a
    newer decision reinstated after this run was queued. ``active_ban`` is
    true when any ban on the target is in force; a kick repair must not
    unban a target that a federation ban now holds.
    """

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
    """Cancel a run whose action is no longer expirable.

    The reason is kept on the run, so the ledger says why a delivery was
    abandoned instead of leaving a terminal row with no explanation.
    """

    async def _work(sess: AsyncSession) -> None:
        await sess.execute(
            _CANCEL_RUN, {"run_id": run_id, "error_detail": error_detail}
        )

    await run_transaction(_work)
