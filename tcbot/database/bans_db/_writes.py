# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Write helpers over the community ban decisions."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

import msgspec
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from tcbot import cfg
from tcbot.database import enforcement_db, moderation_db
from tcbot.database.base import (
    moderation_actions,
    moderation_appeals,
    moderation_messages,
)
from tcbot.database.documents import BanDoc
from tcbot.database.engine import (
    constraint_name,
    db_call,
    run,
    run_transaction,
)
from tcbot.database.types import make_short_id
from tcbot.database.users_cache import ensure_users
from tcbot.utils.logger import get_logger
from tcbot.utils.time_and_date import utc_now

from ._compose import compose_rows
from ._queries import action_by_ref, get_active_ban, get_ban
from ._shared import (
    ACTION_COLUMNS,
    CONSTRAINT_ACTIVE_USER,
    CONSTRAINT_EXTERNAL_REF,
    META_APPEAL_LINK,
    META_DURATION,
    META_PREVIOUS_LOG,
    META_PREVIOUS_PROOF,
    META_REVIEW_MESSAGE,
    META_REVIEW_TIMESTAMP,
    META_UPDATE_COUNT,
    _drop_review_keys,
    _in_force,
    _merge_metadata,
    _slot_holds,
    _slot_is_free,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime

    from sqlalchemy.engine import CursorResult
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.sql.elements import ColumnElement

    from tcbot.database.documents import EvidenceItemDoc

log = get_logger(__name__)


def _json_patch(payload: dict[str, Any]) -> str:
    """Return the JSONB patch that carries *payload* into the metadata."""
    return msgspec.json.encode(payload).decode()


def make_ban_id() -> str:
    """Generate a unique short ID for a new ban record."""
    return make_short_id()


async def _open_case(
    sess: AsyncSession,
    target_id: int,
    admin_id: int,
    reason: str,
    *,
    requires_evidence: bool,
) -> int:
    """Return the open case of the target, or open one for the decision."""
    return await moderation_db.open_case(
        sess,
        target_id,
        admin_id,
        title=f"Community ban of {target_id}",
        summary=reason,
        severity="unknown",
        requires_evidence=requires_evidence,
    )


async def _reuse_existing(
    target_id: int, error: Exception, ban_id: str, *, auto_id: bool
) -> BanDoc:
    """Return the canonical active ban when this insert lost the race."""
    existing = await get_active_ban(target_id)
    if existing is None:
        raise error
    if not auto_id and str(existing.get("ban_id", "")) == str(ban_id):
        # * The explicit id itself is taken, so the caller must not be
        # * handed a record it cannot reference.
        raise error
    log.warning(
        "Concurrent ban for user %d lost the race; reusing ban %s",
        target_id,
        existing.get("ban_id", ""),
    )
    return cast("BanDoc", existing)


async def create_ban(
    target_id: int,
    reason: str,
    admin_id: int,
    proof_msg_id: int,
    log_msg_id: int,
    ban_id: str | None = None,
    *,
    until_date: datetime | None = None,
    duration_str: str | None = None,
    destination_chat_id: int | None = None,
    origin_chat_id: int | None = None,
    action_origin: str = "manual",
    proof_items: Sequence[EvidenceItemDoc] | None = None,
    proof_expected_count: int = 0,
    destination_thread_id: int | None = None,
    enforcement_chat_ids: Sequence[int] | None = None,
) -> BanDoc:
    """Record a new community ban.

    The decision, its case, its archived proof, and its optional apply run
    land in one transaction. ``action_origin`` says whether the decision
    needs the proof: a manual ban does, an automated threshold ban may
    stand on its own.
    """
    auto_id = ban_id is None
    if auto_id:
        ban_id = make_ban_id()
    archive_chat = (
        destination_chat_id if destination_chat_id is not None else cfg.proofs[0]
    )
    archive_thread = (
        destination_thread_id
        if destination_thread_id is not None
        else (cfg.proofs[1] if destination_chat_id is None else None)
    )
    requires_evidence = action_origin != "automated"
    metadata: dict[str, Any] = {
        META_DURATION: duration_str,
        META_UPDATE_COUNT: 0,
    }
    # * One clock reading for the whole decision. The case and proof writes
    # * may take a moment over a network; using a later reading for
    # * created_at could push it past a short deadline and the schema would
    # * refuse the row as already expired.
    now = utc_now()

    async def _work(sess: AsyncSession) -> dict[str, Any] | None:
        case_id = await _open_case(
            sess, target_id, admin_id, reason, requires_evidence=requires_evidence
        )
        upload_id = await moderation_db.archive_proof(
            sess,
            case_id,
            admin_id,
            proof_msg_id,
            archive_chat,
            items=proof_items,
            expected_item_count=proof_expected_count,
            destination_thread_id=archive_thread,
        )
        row = (
            (
                await sess.execute(
                    pg_insert(moderation_actions)
                    .values(
                        action_type="ban",
                        scope_type="community",
                        chat_id=None,
                        origin_chat_id=origin_chat_id,
                        target_user_id=target_id,
                        actor_user_id=admin_id,
                        reason=reason,
                        duration_seconds=moderation_db.remaining_seconds(
                            until_date, now
                        ),
                        created_at=now,
                        expires_at=until_date,
                        status="active",
                        external_ref=ban_id,
                        metadata=metadata,
                        case_id=case_id,
                        evidence_upload_id=upload_id,
                        action_origin=action_origin,
                    )
                    .returning(*ACTION_COLUMNS)
                )
            )
            .mappings()
            .first()
        )
        if row is None:
            return None
        row = dict(row)
        if enforcement_chat_ids is not None:
            row["enforcement_run_id"] = await enforcement_db.queue_run(
                sess,
                action_id=int(row["id"]),
                operation="apply",
                idempotency_key=f"moderation:{row['id']}:apply:v1",
                requested_by_user_id=admin_id,
                chat_ids=enforcement_chat_ids,
            )
        if log_msg_id:
            await sess.execute(
                pg_insert(moderation_messages).values(
                    action_id=row["id"],
                    chat_id=archive_chat,
                    message_id=log_msg_id,
                    message_kind="log",
                    recorded_by_user_id=admin_id,
                )
            )
        # * The investigation ends with its decision. A case that stays
        # * open is picked up by the next decision about the same user,
        # * so the history of the community collapses into one case per
        # * user instead of one case per incident.
        await moderation_db.close_case(sess, case_id, admin_id)
        return dict(row)

    try:
        # * run_transaction already applies the circuit breaker and timeout.
        # * A second db_call would reserve the half-open probe twice.
        row = await run_transaction(_work)
    except Exception as insert_error:
        violated = constraint_name(insert_error)
        if violated == CONSTRAINT_EXTERNAL_REF and auto_id:
            # * The generated id collided with an existing one. The id is
            # * random, so this is vanishingly rare, but it must not fail
            # * the moderation action: the caller never supplied the id,
            # * so it can be swapped for a fresh one and the insert retried.
            ban_id = make_ban_id()
            metadata[META_DURATION] = duration_str
            try:
                row = await run_transaction(_work)
            except Exception as retry_error:
                # * The retry can lose a different race: a concurrent ban
                # * for the same target. That case has its own handling, so
                # * the raw integrity error must not surface as a write
                # * failure.
                if constraint_name(retry_error) != CONSTRAINT_ACTIVE_USER:
                    raise
                return await _reuse_existing(
                    target_id, retry_error, ban_id, auto_id=auto_id
                )
        elif violated != CONSTRAINT_ACTIVE_USER:
            # * Only the one-active-ban-per-user constraint may lose a
            # * race. Any other integrity error is a real defect and
            # * must not be swallowed here.
            raise
        else:
            # * The unique partial index allows only one active ban per
            # * user, so a concurrent ban for the same target loses the
            # * race here. The existing record is the canonical one: the
            # * caller keeps it and the moderation continues.
            return await _reuse_existing(
                target_id, insert_error, ban_id, auto_id=auto_id
            )
    if row is None:
        raise RuntimeError("the ban record was not written")
    docs = await compose_rows([row])
    document = docs[0]
    run_id = row.get("enforcement_run_id")
    if isinstance(run_id, int):
        document["enforcement_run_id"] = run_id
    return document


async def update_ban(
    ban_id: str,
    reason: str,
    admin_id: int,
    new_proof_id: int,
    new_log_id: int = 0,
    old_proof_id: int = 0,
    old_log_id: int = 0,
    *,
    until_date: datetime | None = None,
    duration_str: str | None = None,
    destination_chat_id: int | None = None,
    proof_items: Sequence[EvidenceItemDoc] | None = None,
    proof_expected_count: int = 0,
    destination_thread_id: int | None = None,
    enforcement_chat_ids: Sequence[int] | None = None,
) -> BanDoc | None:
    """Record a re-ban.

    A re-ban is a new decision that supersedes the active one, carries the
    new reason and proof, and opens its own case. The superseded decision
    keeps its reason, actor, and timestamps.
    """
    current = await get_ban(ban_id)
    if current is None:
        return None
    archive_chat = (
        destination_chat_id if destination_chat_id is not None else cfg.proofs[0]
    )
    archive_thread = (
        destination_thread_id
        if destination_thread_id is not None
        else (cfg.proofs[1] if destination_chat_id is None else None)
    )
    proof_id = new_proof_id or old_proof_id
    target_id = cast("int", current.get("target_user_id"))
    metadata: dict[str, Any] = {
        META_DURATION: duration_str,
        META_UPDATE_COUNT: int(current.get("update_count", 0) or 0) + 1,
        META_PREVIOUS_PROOF: old_proof_id or None,
        META_PREVIOUS_LOG: old_log_id or None,
    }
    external_ref = make_ban_id()
    # * Same single clock reading as create_ban: the case and proof writes
    # * must not push created_at past the new deadline.
    now = utc_now()

    async def _work(sess: AsyncSession) -> dict[str, Any] | None:
        case_id = await _open_case(
            sess, target_id, admin_id, reason, requires_evidence=True
        )
        upload_id = await moderation_db.archive_proof(
            sess,
            case_id,
            admin_id,
            proof_id,
            archive_chat,
            items=proof_items if new_proof_id else None,
            expected_item_count=proof_expected_count if new_proof_id else 1,
            destination_thread_id=archive_thread,
        )
        row = (
            (
                await sess.execute(
                    pg_insert(moderation_actions)
                    .values(
                        action_type="ban",
                        scope_type="community",
                        chat_id=None,
                        target_user_id=target_id,
                        actor_user_id=admin_id,
                        reason=reason,
                        duration_seconds=moderation_db.remaining_seconds(
                            until_date, now
                        ),
                        created_at=now,
                        expires_at=until_date,
                        status="active",
                        external_ref=external_ref,
                        metadata=metadata,
                        case_id=case_id,
                        evidence_upload_id=upload_id,
                        supersedes_action_id=current.get("id"),
                        action_origin="manual",
                    )
                    .returning(*ACTION_COLUMNS)
                )
            )
            .mappings()
            .first()
        )
        if row is None:
            return None
        row = dict(row)
        if enforcement_chat_ids is not None:
            row["enforcement_run_id"] = await enforcement_db.queue_run(
                sess,
                action_id=int(row["id"]),
                operation="apply",
                idempotency_key=f"moderation:{row['id']}:apply:v1",
                requested_by_user_id=admin_id,
                chat_ids=enforcement_chat_ids,
            )
        if new_log_id:
            await sess.execute(
                pg_insert(moderation_messages).values(
                    action_id=row["id"],
                    chat_id=archive_chat,
                    message_id=new_log_id,
                    message_kind="log",
                    recorded_by_user_id=admin_id,
                )
            )
        await moderation_db.close_case(sess, case_id, admin_id)
        return dict(row)

    row = await run_transaction(_work)
    if row is None:
        return None
    docs = await compose_rows([row])
    document = docs[0]
    run_id = row.get("enforcement_run_id")
    if isinstance(run_id, int):
        document["enforcement_run_id"] = run_id
    return document


async def set_log_message_id(ban_id: str, log_msg_id: int) -> None:
    """Attach the federation log message to a ban."""
    action = await action_by_ref(ban_id)
    if action is None:
        # * The decision is gone or was renamed. The message reference is
        # * lost, so the mismatch has to be visible.
        log.warning("Federation log message has no ban record for ban_id=%s", ban_id)
        return
    await db_call(
        lambda: run(
            # * The message table is append-only history, so this always adds
            # * a row; the compose read orders by id and takes the newest.
            pg_insert(moderation_messages).values(
                action_id=int(action["id"]),
                chat_id=cfg.logs[0],
                message_id=log_msg_id,
                message_kind="log",
            )
        )
    )


async def deactivate_all_active_bans(
    user_id: int, *, withdraw_pending_appeals: bool = True
) -> int:
    """Revoke the active ban of a user. Returns the number of bans revoked.

    The database keeps one active ban per target, so this revokes the one
    decision that is in force. It is a domain write only: the unban command
    and the appeal-approval path use the queueing variants below so the
    delivery intent lands in the same transaction. A staff unban also
    withdraws any pending appeal in the same transaction; leaving it pending
    would block every later appeal while /check kept showing an unreachable
    review.
    """

    async def _work(sess: AsyncSession) -> int:
        action_ids = select(moderation_actions.c.id).where(
            moderation_actions.c.target_user_id == user_id,
            moderation_actions.c.action_type == "ban",
            moderation_actions.c.status == "active",
        )
        if withdraw_pending_appeals:
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
                moderation_actions.c.target_user_id == user_id,
                moderation_actions.c.action_type == "ban",
                moderation_actions.c.status == "active",
            )
            .values(status="revoked", revoked_at=utc_now())
        )
        return cast("CursorResult", result).rowcount

    return await run_transaction(_work)


async def revoke_ban_and_queue_unban(
    user_id: int,
    requested_by_user_id: int | None,
    chat_ids: Sequence[int],
) -> tuple[int, int | None]:
    """Revoke the active ban and queue its unban delivery in one transaction.

    The revocation is the domain decision; the run is the durable work
    item. They have to land together: a revoked record without a run loses
    the groups that failed the fan-out, and a run without a revoked record
    is cancelled by the worker. Pending appeals are withdrawn in the same
    transaction, and the review slot is released so a stale card cannot
    promise a decision that is already gone.
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


async def set_review_if_absent(ban_id: str, msg_id: int) -> bool:
    """Atomically claim the pending-review slot; return True when claimed.

    The slot lives in the metadata of the decision. The condition is part
    of the UPDATE, so the database decides the winner: two concurrent
    appeal submissions for the same ban cannot both claim the slot,
    because the second one matches no row and reports no affected row.
    A read-then-write would let the second writer overwrite the first.
    """
    patch = _json_patch(
        {
            META_REVIEW_MESSAGE: msg_id,
            META_REVIEW_TIMESTAMP: utc_now().isoformat(),
        }
    )
    affected = await db_call(
        lambda: run(
            moderation_actions.update()
            .where(
                moderation_actions.c.external_ref == ban_id,
                moderation_actions.c.action_type == "ban",
                _slot_is_free(),
            )
            .values(metadata=_merge_metadata(patch))
        )
    )
    return affected > 0


async def clear_review(ban_id: str) -> None:
    """Release the review slot, allowing a new appeal to be submitted.

    Called after an appeal is rejected so the banned user is not permanently
    locked out from submitting a second appeal.
    """
    await db_call(
        lambda: run(
            moderation_actions.update()
            .where(
                moderation_actions.c.external_ref == ban_id,
                moderation_actions.c.action_type == "ban",
            )
            .values(metadata=_drop_review_keys())
        )
    )


async def claim_appeal_decision(ban_id: str, review_msg_id: int) -> bool:
    """Atomically claim one appeal decision; return True when claimed.

    The claim consumes the review slot, so it matches only the row that
    still holds that exact review message. A claim that ends without a
    decision must hand the slot back with :func:`restore_review`.
    """
    affected = await db_call(
        lambda: run(
            moderation_actions.update()
            .where(
                moderation_actions.c.external_ref == ban_id,
                moderation_actions.c.action_type == "ban",
                moderation_actions.c.status == "active",
                _in_force(),
                _slot_holds(review_msg_id),
            )
            .values(metadata=_drop_review_keys())
        )
    )
    return affected > 0


def _open_appeal_exists(action_id: int, appellant_user_id: int) -> ColumnElement[bool]:
    """Return the condition that the decision carries an open appeal.

    An open appeal occupies the decision: the review card of that appeal
    is the one the staff have to decide, so a second submission for the
    same appellant must not file a second open appeal.
    """
    return (
        select(moderation_appeals.c.id)
        .where(
            moderation_appeals.c.action_id == action_id,
            moderation_appeals.c.appellant_user_id == appellant_user_id,
            moderation_appeals.c.status == "pending",
        )
        .exists()
    )


def _decided_appeal_exists() -> ColumnElement[bool]:
    """Return the condition that the decision carries a decided appeal.

    A decided appeal is a closed question: its review card must not come
    back, or a second reviewer could decide it again.
    """
    return (
        select(moderation_appeals.c.id)
        .where(
            moderation_appeals.c.action_id == moderation_actions.c.id,
            moderation_appeals.c.status.in_(("accepted", "rejected", "withdrawn")),
        )
        .exists()
    )


async def restore_review(
    ban_id: str,
    review_msg_id: int,
    review_timestamp: datetime | None = None,
) -> bool:
    """Hand a claimed review slot back; return True when it was restored.

    A staff member who cannot decide (a rank refusal, a database outage)
    must not leave the review card dead. The restore only fills an empty
    slot on a ban that is still active and not yet rejected, so it cannot
    resurrect a review that another reviewer already decided.
    """
    patch = _json_patch(
        {
            META_REVIEW_MESSAGE: review_msg_id,
            META_REVIEW_TIMESTAMP: (review_timestamp or utc_now()).isoformat(),
        }
    )
    affected = await db_call(
        lambda: run(
            moderation_actions.update()
            .where(
                moderation_actions.c.external_ref == ban_id,
                moderation_actions.c.action_type == "ban",
                moderation_actions.c.status == "active",
                _in_force(),
                _slot_is_free(),
                # * A decided appeal is a decision: its review card must
                # * not come back, or a second reviewer could decide it
                # * again.
                ~_decided_appeal_exists(),
            )
            .values(metadata=_merge_metadata(patch))
        )
    )
    return affected > 0


async def submit_appeal(
    ban_id: str,
    appellant_user_id: int,
    appeal_text: str,
    review_message_id: int,
) -> bool:
    """Record an appeal and claim its review slot in one transaction.

    The appeal and the claim have to land together. The claim is the
    gate that lets only one appeal be in flight for a decision, and the
    appeal row is what the reviewer decides on, so a claim without a row
    would leave a review card that no decision can close, and a row
    without a claim would leave a pending appeal that blocks every later
    appeal for the same decision.

    The return value is the result of the claim: ``True`` when this call
    owns the review slot, ``False`` when another submission won it or
    when the decision already carries an open appeal. A losing call
    writes nothing at all.
    """
    patch = _json_patch(
        {
            META_REVIEW_MESSAGE: review_message_id,
            META_REVIEW_TIMESTAMP: utc_now().isoformat(),
        }
    )

    async def _work(sess: AsyncSession) -> bool:
        action_id = await sess.scalar(
            select(moderation_actions.c.id)
            .where(
                moderation_actions.c.external_ref == ban_id,
                moderation_actions.c.action_type == "ban",
            )
            .limit(1)
        )
        if action_id is None:
            return False
        # * The claim carries the conditions, so the database decides the
        # * winner: the update matches only a decision whose slot is free
        # * and that carries no open appeal. Two concurrent submissions
        # * therefore cannot both write a row, and the loser leaves the
        # * decision untouched.
        # * The claim runs on the session of this transaction. A separate
        # * session would commit the claim on its own, so a failure of the
        # * insert below would leave the slot claimed by an appeal row
        # * that does not exist.
        claim = await sess.execute(
            moderation_actions.update()
            .where(
                moderation_actions.c.id == action_id,
                moderation_actions.c.status == "active",
                _in_force(),
                _slot_is_free(),
                ~_open_appeal_exists(action_id, appellant_user_id),
            )
            .values(metadata=_merge_metadata(patch))
        )
        if not cast("CursorResult", claim).rowcount:
            return False
        # * The composite foreign key and the trigger of the table hold
        # * the identity rules: the appellant has to be the banned user,
        # * and the decision has to be an active ban.
        await sess.execute(
            pg_insert(moderation_appeals).values(
                action_id=action_id,
                appellant_user_id=appellant_user_id,
                appeal_text=appeal_text,
                status="pending",
                submitted_at=utc_now(),
            )
        )
        return True

    return await run_transaction(_work)


async def accept_appeal(ban_id: str, reviewer_id: int, note: str = "") -> bool:
    """Accept the pending appeal of a decision; return True when it was pending.

    The rejection counterpart is :func:`set_rejected_by`. Both close the
    appeal, so the history says who decided and when, and the partial
    index that limits one open appeal per decision releases the decision
    for a later appeal.
    """
    affected = await db_call(
        lambda: run(
            moderation_appeals.update()
            .where(
                moderation_appeals.c.action_id
                == select(moderation_actions.c.id)
                .where(moderation_actions.c.external_ref == ban_id)
                .scalar_subquery(),
                moderation_appeals.c.status == "pending",
            )
            .values(
                status="accepted",
                resolved_at=utc_now(),
                reviewed_by_user_id=reviewer_id,
                decision_note=note,
            )
        )
    )
    if affected == 0:
        log.warning("Appeal acceptance found no pending appeal for ban_id=%s", ban_id)
    return affected > 0


async def release_stale_review(ban_id: str, review_message_id: int) -> bool:
    """Withdraw the stale appeal of a decision and free its review slot.

    A review card that nobody answered for a long time is stale. The
    user is then allowed to appeal again, but the open appeal of the
    stale card still occupies the slot of the decision, so it has to be
    withdrawn first. Both writes land in one transaction: a withdrawn
    appeal without a free slot would leave the decision unappealable.

    The release only matches the slot that was judged stale. A newer
    appeal can replace the slot between the caller's read and this write,
    and that card must stay decidable.
    """
    withdrawn = False

    async def _work(sess: AsyncSession) -> None:
        nonlocal withdrawn
        # * The slot condition is checked first: only the decision that still
        # * holds the stale card may be released, and only then is the appeal
        # * it belongs to withdrawn.
        result = await sess.execute(
            moderation_actions.update()
            .where(
                moderation_actions.c.external_ref == ban_id,
                moderation_actions.c.action_type == "ban",
                _slot_holds(review_message_id),
            )
            .values(metadata=_drop_review_keys())
        )
        if cast("CursorResult", result).rowcount == 0:
            return
        appeal_result = await sess.execute(
            moderation_appeals.update()
            .where(
                moderation_appeals.c.action_id
                == select(moderation_actions.c.id)
                .where(moderation_actions.c.external_ref == ban_id)
                .scalar_subquery(),
                moderation_appeals.c.status == "pending",
            )
            .values(status="withdrawn", resolved_at=utc_now())
        )
        withdrawn = cast("CursorResult", appeal_result).rowcount > 0

    await run_transaction(_work)
    return withdrawn


async def set_rejected_by(ban_id: str, admin_id: int, admin_name: str) -> None:
    """Persist the rejector identity and rejection timestamp on a ban document.

    Called on appeal reject so the audit trail is preserved even if the log
    message is later deleted or the log channel is unavailable.
    """
    affected = await db_call(
        lambda: run(
            moderation_appeals.update()
            .where(
                moderation_appeals.c.action_id
                == select(moderation_actions.c.id)
                .where(moderation_actions.c.external_ref == ban_id)
                .scalar_subquery(),
                moderation_appeals.c.status == "pending",
            )
            .values(
                status="rejected",
                resolved_at=utc_now(),
                reviewed_by_user_id=admin_id,
                decision_note=admin_name,
            )
        )
    )
    if affected == 0:
        # * The appeal was already decided or the decision was never
        # * filed. The reviewer believes the rejection was persisted, so
        # * the mismatch has to be visible.
        log.warning("Appeal rejection found no pending appeal for ban_id=%s", ban_id)


async def set_appeal_log_msg(
    ban_id: str,
    msg_id: int,
    appeal_link: str = "",
) -> None:
    """Attach appeal-related metadata to a ban record."""
    patch = _json_patch({META_APPEAL_LINK: appeal_link}) if appeal_link else ""

    async def _work(sess: AsyncSession) -> None:
        action = await sess.scalar(
            select(moderation_actions.c.id)
            .where(
                moderation_actions.c.external_ref == ban_id,
                moderation_actions.c.action_type == "ban",
            )
            .limit(1)
        )
        if action is None:
            log.warning("Appeal log message has no ban record for ban_id=%s", ban_id)
            return
        # * The metadata and the message reference land in one
        # * transaction: a crash between the two writes would leave the
        # * decision pointing at a message the history does not hold.
        if patch:
            await sess.execute(
                moderation_actions.update()
                .where(moderation_actions.c.id == action)
                .values(metadata=_merge_metadata(patch))
            )
        await sess.execute(
            # * Append-only history: every appeal keeps its own log reference.
            pg_insert(moderation_messages).values(
                action_id=action,
                chat_id=cfg.logs[0],
                message_id=msg_id,
                message_kind="appeal_log",
            )
        )

    await run_transaction(_work)
