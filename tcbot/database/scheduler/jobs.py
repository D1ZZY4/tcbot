# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Scheduled maintenance jobs: expiry, erasure, retention, and cleanup."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy import text

from tcbot.database.base import chat_members
from tcbot.database.cache import (
    effective_role_cache,
    user_locale_cache,
    user_mention_cache,
)
from tcbot.database.engine import run_transaction
from tcbot.database.queues_db import expire_stale_requests
from tcbot.utils.dispatch import throw_if_cancelled
from tcbot.utils.logger import get_logger
from tcbot.utils.time_and_date import utc_now

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

log = get_logger(__name__)

# ────────────────────────────── Jobs ────────────────────────────── #

# * Ceiling for one warn-expiry delete batch: a hung database must fail the
# * run loudly instead of wedging the scheduler worker forever.
_EXPIRE_OP_TIMEOUT_S: float = 60.0
# * The registry entry allows 300 s for the retention sweep. The sweep walks
# * every enabled policy, so the budget has to reach the transaction.
_RETENTION_OP_TIMEOUT_S: float = 300.0
# * The registry entry allows 120 s for one erasure batch. The batch is 25
# * account deletions, and each one anonymizes rows across the community
# * tables, so the budget matches the registered contract.
_ERASURE_OP_TIMEOUT_S: float = 120.0
# * How long a cached profile is kept before the daily cleanup drops it.
# * It replaces the TTL pruning the MongoDB deployment did on its own.
_MEMBER_CACHE_EXPIRE_DAYS: int = 90


async def expire_due_decisions() -> None:
    """Expire the decisions and the role assignments that ran out.

    A decision carries its own expiry, so the sweep only has to move the
    records whose deadline passed: the ban and the mute decisions go to
    ``expired`` and a revoke enforcement run is queued for every group the
    community still manages, and the role assignments go to ``expired``
    with an audit event behind them. A warning that runs out stops
    counting towards the threshold on its own: the counter reads the
    expiry at query time, so the history stays readable and the sweep
    never has to rewrite it.

    Called daily by APScheduler.
    """
    try:
        # * The budget belongs to the transaction itself: the run-level
        # * timeout would otherwise fire first and report a shorter
        # * deadline than the one the operator is told about.
        summary = await run_transaction(
            lambda sess: _expire_transaction(sess),
            timeout=_EXPIRE_OP_TIMEOUT_S,
        )
    except TimeoutError:
        log.exception(
            "Expiry sweep timed out after %ds; no expiry completed.",
            _EXPIRE_OP_TIMEOUT_S,
        )
        # * A hung expiry must fail the run, not report success: returning
        # * normally would report a completed expiry while the decisions
        # * were never expired.
        raise RuntimeError(
            "Expiry sweep timed out: no records expired; see errors above."
        ) from None
    except Exception as exc:
        # * The transaction rolled back, so the decisions still agree with
        # * their expiry. Surface the failure: the caller must not read
        # * the partial state as a completed expiry.
        log.exception("Expiry sweep failed; the sweep was rolled back.")
        raise RuntimeError(
            "Expiry sweep incomplete: the sweep was rolled back; see errors above."
        ) from exc
    log.info("Expiry sweep: %s.", summary)


async def _expire_transaction(sess: AsyncSession) -> dict[str, Any]:
    """Move the due records to their expired state inside one transaction.

    The decisions and the role assignments are expired by the database, so
    the transition rules live in one place. The revoke runs are queued in
    the same transaction, so a decision can never be expired without the
    job that lifts the restriction on Telegram.

    A transaction-level advisory lock serialises the sweep across every
    live bot instance, so two schedulers cannot expire the same records
    and queue duplicate revokes.
    """
    locked = await sess.scalar(
        text("SELECT pg_try_advisory_xact_lock(hashtextextended(:scope, 0))"),
        {"scope": "tcbot:expiry"},
    )
    if not locked:
        log.info("Expiry sweep skipped: another instance owns the lock.")
        return {"skipped": True}
    decisions = await sess.execute(
        text("SELECT expire_due_moderation_actions_and_queue_revokes()")
    )
    roles = await sess.execute(text("SELECT expire_due_role_assignments_and_audit()"))
    return {
        "decisions": _summary_of(decisions),
        "role_assignments": _summary_of(roles),
    }


def _summary_of(result: Any) -> dict[str, Any]:
    """Return the JSON summary a database expiry function reports."""
    payload = result.scalar()
    if isinstance(payload, dict):
        return payload
    return {"count": int(payload or 0)}


async def expire_old_warns(warn_expiry_days: int) -> None:
    """Retired name of :func:`expire_due_decisions`.

    The sweep used to patch the warnings that had no deadline, which the
    community schema forbids: the expiry of a decision is a fact of it.
    The warnings now carry their deadline from the moment they are filed,
    so the sweep only expires the records that ran out. The old name
    stays importable because a persisted job record still points at it.
    """
    await expire_due_decisions()


async def expire_stale_records() -> None:
    """Delete the rows PostgreSQL cannot expire on its own.

    The membership cache is the only table that grows without bound: the
    query that reads it filters on the last sighting, so a stale row is
    only storage. The erasure queue is processed here as well, so an
    account the user deleted on Telegram is anonymized even when the
    scheduler was down.

    Called daily by APScheduler.
    """
    profile_cutoff = utc_now() - timedelta(days=_MEMBER_CACHE_EXPIRE_DAYS)
    try:
        async with asyncio.timeout(_EXPIRE_OP_TIMEOUT_S):
            # * The two sweeps touch different tables, so they run
            # * concurrently and the run waits for both.
            members_res, erasures_res = await asyncio.gather(
                run_transaction(
                    lambda sess: _cleanup_members(sess, profile_cutoff),
                    timeout=None,
                ),
                # * The transaction carries its own timeout, so it has to
                # * be switched off here as well: the run-level timeout
                # * is the bound that applies to the sweep.
                _run_erasure_sweep(),
                return_exceptions=True,
            )
    except TimeoutError:
        log.exception(
            "Stale record cleanup timed out after %ds; no cleanup completed.",
            _EXPIRE_OP_TIMEOUT_S,
        )
        raise RuntimeError(
            "Stale record cleanup timed out: nothing expired; see errors above."
        ) from None
    # ! CRITICAL: a cancelled cleanup must propagate, not report success.
    throw_if_cancelled((members_res, erasures_res))
    erased, erased_ids = _erasure_result(erasures_res)
    # * The invalidation runs before the failure verdict. The erasure and
    # * the membership delete are separate transactions, so a failed
    # * membership delete must not keep an erased name served from the two
    # * cache layers for the whole TTL.
    _invalidate_erased(erased_ids)
    failures = [r for r in (members_res, erasures_res) if isinstance(r, BaseException)]
    if failures:
        for failure in failures:
            log.error("Stale record cleanup failed: %s", failure)
        raise RuntimeError(
            "Stale record cleanup incomplete; see errors above."
        ) from failures[0]
    removed = members_res if isinstance(members_res, int) else 0
    log.info(
        "Stale record cleanup: removed %d stale memberships and processed %d erasures.",
        removed,
        erased,
    )


async def process_erasure_queue() -> None:
    """Process the queued Telegram account erasures and drop their caches.

    The registry registers ``user.erasure`` as a ten-minute application
    job. The daily cleanup drains the queue as well, so a request is never
    lost, but a queued deletion must not wait a day for the maintenance
    window. The cached profile and role of every processed account are
    invalidated only after the transaction commits, so a concurrent read
    cannot restore the erased name.
    """
    try:
        async with asyncio.timeout(_ERASURE_OP_TIMEOUT_S):
            erased, erased_ids = await _run_erasure_sweep()
    except asyncio.CancelledError:
        raise
    except TimeoutError:
        log.exception(
            "Erasure sweep timed out after %ds.",
            _ERASURE_OP_TIMEOUT_S,
        )
        raise RuntimeError("Erasure sweep timed out.") from None
    except Exception:
        log.exception("Erasure sweep failed.")
        raise
    _invalidate_erased(erased_ids)
    if erased:
        log.info("Erasure sweep processed %d request(s).", erased)


def _erasure_result(result: object) -> tuple[int, list[int]]:
    """Return the erasure batch outcome of a gathered sweep step."""
    if not isinstance(result, tuple) or len(result) != 2:
        return 0, []
    erased, erased_ids = result
    if not isinstance(erased, int) or not isinstance(erased_ids, list):
        return 0, []
    return erased, [int(user_id) for user_id in erased_ids]


def _invalidate_erased(user_ids: list[int]) -> None:
    """Drop the cached profile and role of every erased account."""
    for user_id in user_ids:
        user_mention_cache.invalidate(user_id)
        effective_role_cache.invalidate(user_id)
        user_locale_cache.invalidate(user_id)


async def _cleanup_members(sess: AsyncSession, cutoff: Any) -> int:
    """Delete stale membership rows under a cross-instance lock."""
    locked = await sess.scalar(
        text("SELECT pg_try_advisory_xact_lock(hashtextextended(:scope, 0))"),
        {"scope": "tcbot:cleanup:members"},
    )
    if not locked:
        return 0
    result = await sess.execute(
        chat_members.delete().where(
            chat_members.c.last_seen_at.isnot(None),
            chat_members.c.last_seen_at < cutoff,
        )
    )
    return int(getattr(result, "rowcount", 0) or 0)


async def _sweep_erasures(sess: AsyncSession) -> tuple[int, list[int]]:
    """Process the erasure queue under a cross-instance lock.

    Returns the number of processed requests and the user ids the batch
    covered. The caller invalidates those ids only after the transaction
    commits, so a concurrent cache fill cannot restore an erased name.
    """
    locked = await sess.scalar(
        text("SELECT pg_try_advisory_xact_lock(hashtextextended(:scope, 0))"),
        {"scope": "tcbot:cleanup:erasures"},
    )
    if not locked:
        return 0, []
    started_at = await sess.scalar(text("SELECT now()"))
    pending = await sess.execute(
        text(
            "SELECT user_id FROM telegram_user_erasures "
            "WHERE status = 'pending' "
            # * The sweep processes the oldest requests first, so the same
            # * order keeps the cache invalidation aligned with the batch
            # * the database function is about to process.
            "ORDER BY requested_at, id "
            "LIMIT 25"
        )
    )
    erased_ids = [int(row[0]) for row in pending]
    result = await sess.execute(text("SELECT sweep_pending_user_erasures(25)"))
    erased_count = int(result.scalar() or 0)
    # * A request inserted between the pre-read and the function call can
    # * still be erased by the batch. Read back every account completed in
    # * this transaction so its caches are invalidated too; invalidating an
    # * extra id is harmless, while missing one serves the old profile for
    # * the whole cache TTL.
    if started_at is not None:
        completed = await sess.execute(
            text(
                "SELECT user_id FROM telegram_user_erasures "
                "WHERE status = 'completed' AND processed_at >= :started_at"
            ),
            {"started_at": started_at},
        )
        erased_ids.extend(int(row[0]) for row in completed)
    return erased_count, sorted(set(erased_ids))


async def _run_erasure_sweep() -> tuple[int, list[int]]:
    """Drain one erasure batch in its own transaction.

    The default transaction bound is 20 s, but the registry allows 120 s
    for a batch that anonymizes rows across the community tables, so the
    caller's run-level budget is the one that applies.
    """
    return await run_transaction(_sweep_erasures, timeout=None)


async def expire_promotion_requests() -> None:
    """Mark pending promotion requests past their TTL as expired.

    The update is idempotent, so a second instance running the same tick
    only sees the rows the first one already moved. The stale request is
    also expired lazily when a new request is enqueued and when a list is
    read, but the schedule keeps the history tidy while nobody looks.
    """
    try:
        expired = await expire_stale_requests()
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("Promotion request expiry sweep failed.")
        raise
    if expired:
        log.info("Promotion request expiry sweep closed %d request(s).", expired)


async def sweep_retention() -> None:
    """Apply the retention policies of the schema through the job registry.

    The policies remove runtime telemetry past its window and prune the
    expired MTProto session state. The registry claim keeps the sweep from
    running twice when another owner (pg_cron or another instance) fires at
    the same time, and the run lands in ``scheduled_job_runs`` so a failed
    sweep is visible instead of silently leaving the tables to grow.
    """
    try:
        async with asyncio.timeout(_RETENTION_OP_TIMEOUT_S):
            # * The registry entry allows a 300 s sweep. The default
            # * transaction bound is 20 s, so the run-level budget is the
            # * one that applies to a large telemetry backlog.
            # * The run key is day-scoped: two instances that fire a few
            # * minutes apart still produce one sweep for the day.
            run_key = f"retention.sweep:{utc_now().strftime('%Y%m%d')}"
            report = await run_transaction(
                lambda sess: sess.scalar(
                    text("SELECT run_scheduled_job('retention.sweep', :run_key)"),
                    {"run_key": run_key},
                ),
                timeout=None,
            )
    except asyncio.CancelledError:
        raise
    except TimeoutError:
        log.exception(
            "Retention sweep timed out after %ds.",
            _RETENTION_OP_TIMEOUT_S,
        )
        raise RuntimeError("Retention sweep timed out.") from None
    except Exception:
        log.exception("Retention sweep failed.")
        raise
    removed = 0
    if isinstance(report, dict):
        value = report.get("affected")
        if isinstance(value, int):
            removed = value
    log.info("Retention sweep removed %d row(s).", removed)


async def _cleanup_old_records() -> None:
    """No-op shim for the retired weekly membership-cache cleanup job.

    The cleanup of the stale memberships is now handled by the daily
    :func:`expire_stale_records` job, because PostgreSQL has no TTL index.
    The legacy schedule is removed on startup in ``_reconcile_schedules``;
    this function stays importable so that the job store can still
    deserialize a record that points at it. Without the symbol, loading
    such a record raises ``AttributeError`` and the whole reconciliation
    fails, leaving the new schedule unregistered.
    """
    log.info(
        "DB cleanup job called but is now a no-op; "
        "cleanup is handled by the daily expire_stale_records job."
    )
