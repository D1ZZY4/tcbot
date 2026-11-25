# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Community mute helpers over the moderation decision tables.

A mute is one decision in ``moderation_actions``. The live state and the
history are the same row: an active mute is a decision whose status is
``active``, and lifting it moves the row to ``revoked``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from tcbot.database import enforcement_ledger, moderation_db
from tcbot.database.base import moderation_actions
from tcbot.database.documents import ActiveMuteDoc, MuteDoc
from tcbot.database.engine import (
    constraint_name,
    db_call,
    fetch_all,
    fetch_one,
    fetch_value,
    run_transaction,
)
from tcbot.database.types import ChatId, UserId
from tcbot.database.users_cache import ensure_users
from tcbot.utils.logger import get_logger
from tcbot.utils.time_and_date import utc_now

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime

    from sqlalchemy.ext.asyncio import AsyncSession

    from tcbot.database.documents import EvidenceItemDoc

log = get_logger(__name__)

# ──────────────────────────── Tables ────────────────────────────── #
# * The surrogate primary key stays out of the returned documents: the
# * helpers expose the community fields, not the storage identity.
_MUTE_COLUMNS = (
    moderation_actions.c.id,
    moderation_actions.c.external_ref,
    moderation_actions.c.target_user_id,
    moderation_actions.c.actor_user_id,
    moderation_actions.c.reason,
    moderation_actions.c.duration_seconds,
    moderation_actions.c.created_at,
    moderation_actions.c.expires_at,
    moderation_actions.c.status,
    moderation_actions.c.case_id,
    moderation_actions.c.origin_chat_id,
    moderation_actions.c.metadata,
)

# * The live mute row is keyed by the muted user, so the whole row is
# * the document: there is no surrogate id to hide.

# * Name of the partial unique index that keeps one active mute per
# * target. A second decision has to supersede the first one.
_CONSTRAINT_ACTIVE_MUTE: str = "uq_moderation_actions_active_mute"


# ──────────────────────────── Mutations ─────────────────────────── #
# * Functions that create or modify mute decisions.
# * Primarily used for audit logging of moderation actions.


async def record_mute(
    user_id: int,
    chat_id: int,
    reason: str,
    admin_id: int,
    *,
    until: datetime | None = None,
    requested_duration_seconds: int | None = None,
    enforcement_chat_ids: Sequence[int] | None = None,
    proof_items: Sequence[EvidenceItemDoc] | None = None,
    proof_expected_count: int = 0,
    destination_chat_id: int = 0,
    destination_thread_id: int | None = None,
    rule_item_ids: Sequence[int] = (),
    rule_selection_note: str | None = None,
) -> tuple[int, int | None]:
    """Record a community mute and return its decision and delivery run.

    The deadline is stored as an absolute expiry, and the duration the
    decision shows is derived from it, so the two can never disagree. The
    duration the moderator requested is kept as metadata, because the
    stored duration is the remaining lifetime and a superseding mute can
    extend it. A permanent mute has no expiry and no duration.

    The decision, the case that holds it, and the optional apply run land
    in one transaction. A run without a decision would be cancelled, and a
    decision without the run would lose the groups that failed the first
    delivery.
    """

    async def _work(sess: AsyncSession) -> tuple[int, int | None]:
        # * Serialise the read-supersede-insert sequence per user. Without
        # * the lock both concurrent writers read the same active mute and
        # * the trigger rejects the second supersede with a raw error that
        # * is not the unique-constraint retry the caller knows.
        await sess.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:scope, 0))"),
            {"scope": f"mute:{user_id}"},
        )
        # * Read the clock after the lock and hold the active row: an
        # * unmute may have revoked it while this writer waited, and the
        # * trigger would reject a supersession of a no-longer-active row.
        now = utc_now()
        case_id = await _open_case(sess, user_id, admin_id, reason)
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
        previous = (
            (
                await sess.execute(
                    select(
                        moderation_actions.c.id,
                        moderation_actions.c.expires_at,
                    )
                    .where(
                        moderation_actions.c.target_user_id == user_id,
                        moderation_actions.c.action_type == "mute",
                        moderation_actions.c.status == "active",
                        # * A mute that ran out is not in force any more,
                        # * even before the sweep moves it to its expired
                        # * state. Superseding it would target a row that
                        # * is no longer active and fail the whole write.
                        (moderation_actions.c.expires_at.is_(None))
                        | (moderation_actions.c.expires_at > now),
                    )
                    .with_for_update()
                )
            )
            .mappings()
            .first()
        )
        expires_at = until
        supersedes: int | None = None
        if previous is not None:
            supersedes = int(previous["id"])
            stored = previous["expires_at"]
            if stored is None or until is None:
                # * A permanent mute outranks every deadline: the new
                # * decision carries no expiry, so the restriction never
                # * runs out on its own.
                expires_at = None
            elif until > stored:
                expires_at = until
            else:
                expires_at = stored
        row = (
            (
                await sess.execute(
                    pg_insert(moderation_actions)
                    .values(
                        action_type="mute",
                        scope_type="community",
                        chat_id=None,
                        origin_chat_id=chat_id,
                        target_user_id=user_id,
                        actor_user_id=admin_id,
                        reason=reason,
                        duration_seconds=moderation_db.remaining_seconds(
                            expires_at, now
                        ),
                        created_at=now,
                        expires_at=expires_at,
                        status="active",
                        case_id=case_id,
                        evidence_upload_id=upload_id,
                        supersedes_action_id=supersedes,
                        action_origin="manual",
                        metadata=(
                            {"requested_duration_seconds": requested_duration_seconds}
                            if requested_duration_seconds is not None
                            else {}
                        ),
                    )
                    .returning(moderation_actions.c.id)
                )
            )
            .mappings()
            .first()
        )
        if row is None:
            raise RuntimeError("the mute decision was not written")
        await moderation_db.link_case_rules(
            sess, case_id, rule_item_ids, admin_id, chat_id, rule_selection_note
        )
        run_id: int | None = None
        if enforcement_chat_ids is not None:
            run_id = await enforcement_ledger.queue_run(
                sess,
                action_id=int(row["id"]),
                operation="apply",
                idempotency_key=f"moderation:{row['id']}:apply:v1",
                requested_by_user_id=admin_id,
                chat_ids=enforcement_chat_ids,
            )
        # * The investigation ends with its decision: an open case is
        # * picked up by the next decision about the same user, so the
        # * history would collapse into one case per user.
        await moderation_db.close_case(sess, case_id, admin_id)
        return int(row["id"]), run_id

    try:
        return await run_transaction(_work)
    except Exception as exc:
        if constraint_name(exc) != _CONSTRAINT_ACTIVE_MUTE:
            raise
        # * A concurrent mute won the race and committed its decision
        # * first. The retry reads the mute that is now in force and
        # * supersedes it, so both moderators end up with one mute and a
        # * readable history.
        log.info(
            "Concurrent mute for user %d lost the race; retrying against it.",
            user_id,
        )
        return await run_transaction(_work)


async def _open_case(
    sess: AsyncSession, target_id: int, admin_id: int, reason: str
) -> int:
    """Return the open case of the target, or open one for the decision."""
    return await moderation_db.open_case(
        sess,
        target_id,
        admin_id,
        title=f"Community mute of {target_id}",
        summary=reason,
        severity="unknown",
        requires_evidence=False,
    )


# ──────────────────────── Active mute store ─────────────────────── #
# * The active mute is the decision whose status is ``active`` and whose
# * expiry has not passed. The decision is written before the restrict
# * fan-out, so no group is touched when the record cannot persist.
# * The expiry is read at query time, so no background cleanup job is
# * needed to keep the view honest.


async def revoke_mute_and_queue_unmute(
    user_id: int,
    requested_by_user_id: int | None,
    chat_ids: Sequence[int],
) -> tuple[int, int | None]:
    """Revoke the active mute and queue its restore in one transaction.

    The revocation is the domain decision; the run is the durable work
    item. They land together, so a partial restore keeps every group it
    still has to reach even though the mute record is already revoked.
    A record revoked without a run would lose the groups that failed the
    fan-out, and a run without a revoked record would be cancelled by the
    worker because the action is still in force.
    """
    now = utc_now()

    async def _work(sess: AsyncSession) -> tuple[int, int | None]:
        action_ids = list(
            (
                await sess.scalars(
                    select(moderation_actions.c.id)
                    .where(
                        moderation_actions.c.target_user_id == user_id,
                        moderation_actions.c.action_type == "mute",
                        moderation_actions.c.status == "active",
                    )
                    .with_for_update()
                )
            ).all()
        )
        if not action_ids:
            return 0, None
        # * The run references the acting staff member. An account the
        # * member cache has never seen must not fail the unmute on a
        # * foreign key, so the identity row joins this transaction.
        await ensure_users(sess, requested_by_user_id or 0)
        result = await sess.execute(
            moderation_actions.update()
            .where(
                moderation_actions.c.id.in_(action_ids),
                moderation_actions.c.status == "active",
            )
            .values(status="revoked", revoked_at=now)
        )
        revoked = int(getattr(result, "rowcount", 0) or 0)
        if revoked == 0:
            return 0, None
        run_id: int | None = None
        for action_id in action_ids:
            queued = await enforcement_ledger.queue_run(
                sess,
                action_id=int(action_id),
                operation="revoke",
                idempotency_key=f"moderation:{action_id}:revoke:manual:v1",
                requested_by_user_id=requested_by_user_id,
                chat_ids=chat_ids,
            )
            run_id = run_id or queued
        return revoked, run_id

    return await run_transaction(_work)


async def get_active_mute(user_id: int) -> ActiveMuteDoc | None:
    """Return the active mute for a user, or None if none exists or has expired."""
    now = utc_now()
    row = await db_call(
        lambda: fetch_one(
            select(
                moderation_actions.c.target_user_id,
                moderation_actions.c.expires_at,
                moderation_actions.c.created_at,
            ).where(
                moderation_actions.c.target_user_id == UserId(user_id),
                moderation_actions.c.action_type == "mute",
                moderation_actions.c.status == "active",
                (moderation_actions.c.expires_at.is_(None))
                | (moderation_actions.c.expires_at > now),
            )
        )
    )
    if row is None:
        return None
    return ActiveMuteDoc(
        user_id=UserId(int(row["target_user_id"])),
        until_date=row.get("expires_at"),
        timestamp=row["created_at"],
    )


async def active_mute_docs() -> list[ActiveMuteDoc]:
    """Return all currently active mute records (used for group-connect replay).

    Expired timed mutes (``expires_at <= now``) are excluded at query time.
    """
    now = utc_now()
    rows = await db_call(
        lambda: fetch_all(
            select(
                moderation_actions.c.target_user_id,
                moderation_actions.c.expires_at,
                moderation_actions.c.created_at,
            ).where(
                moderation_actions.c.action_type == "mute",
                moderation_actions.c.status == "active",
                (moderation_actions.c.expires_at.is_(None))
                | (moderation_actions.c.expires_at > now),
            )
        )
    )
    return [
        ActiveMuteDoc(
            user_id=UserId(int(row["target_user_id"])),
            until_date=row.get("expires_at"),
            timestamp=row["created_at"],
        )
        for row in rows
    ]


# ─────────────────────── Per-user history ───────────────────────── #


async def user_mutes(
    user_id: int, *, skip: int = 0, limit: int | None = None
) -> list[MuteDoc]:
    """Return every mute record for a user, newest first.

    ``limit=None`` returns the full list (backwards compatible).
    """
    stmt = (
        select(*_MUTE_COLUMNS)
        .where(
            moderation_actions.c.target_user_id == user_id,
            moderation_actions.c.action_type == "mute",
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
    return [_compose_mute(row) for row in rows]


async def user_mute_count(user_id: int) -> int:
    """Count every mute ever logged against the user."""
    total = await db_call(
        lambda: fetch_value(
            select(func.count())
            .select_from(moderation_actions)
            .where(
                moderation_actions.c.target_user_id == user_id,
                moderation_actions.c.action_type == "mute",
            )
        )
    )
    return int(total or 0)


def _compose_mute(row: dict[str, Any]) -> MuteDoc:
    """Return the mute document of one decision row."""
    origin = row.get("origin_chat_id")
    metadata = row.get("metadata")
    requested = (
        metadata.get("requested_duration_seconds")
        if isinstance(metadata, dict)
        else None
    )
    return MuteDoc(
        target_user_id=UserId(int(row["target_user_id"])),
        chat_id=ChatId(int(origin)) if origin is not None else None,
        reason=str(row["reason"]),
        actor_user_id=UserId(int(row["actor_user_id"])),
        timestamp=cast("datetime", row["created_at"]),
        duration_secs=cast("int | None", row.get("duration_seconds")),
        requested_duration_secs=(
            int(requested) if isinstance(requested, int | str) else None
        ),
    )
