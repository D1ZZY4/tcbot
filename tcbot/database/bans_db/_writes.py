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
from tcbot.database.base import (
    moderation_actions,
    moderation_appeals,
    moderation_cases,
    moderation_evidence_items,
    moderation_evidence_uploads,
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
    _merge_metadata,
    _slot_holds,
    _slot_is_free,
)

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy.engine import CursorResult
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.sql.elements import ColumnElement

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
    existing = (
        (
            await sess.execute(
                select(moderation_cases.c.id)
                .where(
                    moderation_cases.c.subject_user_id == target_id,
                    moderation_cases.c.status.in_(
                        ("open", "collecting_evidence", "under_review")
                    ),
                )
                .order_by(moderation_cases.c.created_at.desc())
                .limit(1)
            )
        )
        .mappings()
        .first()
    )
    if existing is not None:
        return int(existing["id"])

    created = (
        (
            await sess.execute(
                pg_insert(moderation_cases)
                .values(
                    subject_user_id=target_id,
                    case_type="rule_violation",
                    title=f"Community ban of {target_id}",
                    summary=reason,
                    severity="unknown",
                    status="collecting_evidence",
                    source="manual",
                    opened_by_user_id=admin_id,
                    requires_evidence=requires_evidence,
                )
                .returning(moderation_cases.c.id)
            )
        )
        .mappings()
        .first()
    )
    if created is None:
        raise RuntimeError("the moderation case was not written")
    return int(created["id"])


async def _archive_proof(
    sess: AsyncSession,
    case_id: int,
    admin_id: int,
    proof_message_id: int,
    destination_chat_id: int,
) -> int | None:
    """Archive one proof message and return the batch id.

    The batch walks the lifecycle of the table: it is queued when it is
    written, the worker claims it, the archived item lands, and the
    batch closes as completed once its items are in place.
    """
    if not proof_message_id or not destination_chat_id:
        return None

    upload_id = (
        (
            await sess.execute(
                pg_insert(moderation_evidence_uploads)
                .values(
                    case_id=case_id,
                    uploaded_by_user_id=admin_id,
                    destination_chat_id=destination_chat_id,
                    expected_item_count=1,
                    is_required=True,
                    status="queued",
                )
                .returning(moderation_evidence_uploads.c.id)
            )
        )
        .mappings()
        .first()
    )
    if upload_id is None:
        return None
    batch_id = int(upload_id["id"])

    await sess.execute(
        moderation_evidence_uploads.update()
        .where(moderation_evidence_uploads.c.id == batch_id)
        .values(status="uploading")
    )
    await sess.execute(
        pg_insert(moderation_evidence_items).values(
            upload_id=batch_id,
            destination_chat_id=destination_chat_id,
            archive_message_id=proof_message_id,
            media_type="photo",
            item_order=0,
        )
    )
    await sess.execute(
        moderation_evidence_uploads.update()
        .where(moderation_evidence_uploads.c.id == batch_id)
        .values(status="completed", primary_message_id=proof_message_id)
    )
    return batch_id


def _duration_seconds(until_date: datetime | None) -> int | None:
    """Return the remaining lifetime of a decision in whole seconds."""
    if until_date is None:
        return None
    remaining = int((until_date - utc_now()).total_seconds())
    return max(remaining, 0)


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
) -> BanDoc:
    """Record a new community ban.

    The decision, the case that holds it, and the archived proof land in
    one transaction: a ban without a case or without its proof is not a
    state the community may hold.

    ``action_origin`` says who took the decision. A manual ban needs the
    archived proof; an automated one, such as the ban a warning
    threshold triggers, may stand on its own as long as the case does
    not demand the evidence.
    """
    auto_id = ban_id is None
    if auto_id:
        ban_id = make_ban_id()
    archive_chat = (
        destination_chat_id if destination_chat_id is not None else cfg.proofs[0]
    )
    requires_evidence = action_origin != "automated"
    metadata: dict[str, Any] = {
        META_DURATION: duration_str,
        META_UPDATE_COUNT: 0,
    }

    async def _work(sess: AsyncSession) -> dict[str, Any] | None:
        case_id = await _open_case(
            sess, target_id, admin_id, reason, requires_evidence=requires_evidence
        )
        upload_id = await _archive_proof(
            sess, case_id, admin_id, proof_msg_id, archive_chat
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
                        duration_seconds=_duration_seconds(until_date),
                        created_at=utc_now(),
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
        return dict(row)

    try:
        # * run_transaction already runs through the circuit breaker and
        # * the timeout. Wrapping it in a second db_call would reserve the
        # * half-open probe twice, so the inner call would be rejected
        # * without reaching the database and the outer one would close
        # * the circuit as if the service had answered.
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
    return docs[0]


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
) -> BanDoc | None:
    """Record a re-ban.

    A re-ban is a new decision that supersedes the active one: the old
    action keeps its reason, actor, and timestamps, so the history of the
    case stays readable. The new decision carries the new reason and the
    new proof.
    """
    current = await get_ban(ban_id)
    if current is None:
        return None
    archive_chat = (
        destination_chat_id if destination_chat_id is not None else cfg.proofs[0]
    )
    proof_id = new_proof_id or old_proof_id
    metadata: dict[str, Any] = {
        META_DURATION: duration_str,
        META_UPDATE_COUNT: int(current.get("update_count", 0) or 0) + 1,
        META_PREVIOUS_PROOF: old_proof_id or None,
        META_PREVIOUS_LOG: old_log_id or None,
    }
    external_ref = make_ban_id()

    async def _work(sess: AsyncSession) -> dict[str, Any] | None:
        case_id = int(current.get("case_id") or 0)
        upload_id = await _archive_proof(
            sess, case_id, admin_id, proof_id, archive_chat
        )
        row = (
            (
                await sess.execute(
                    pg_insert(moderation_actions)
                    .values(
                        action_type="ban",
                        scope_type="community",
                        chat_id=None,
                        target_user_id=cast("int", current.get("banned_user_id")),
                        actor_user_id=admin_id,
                        reason=reason,
                        duration_seconds=_duration_seconds(until_date),
                        created_at=utc_now(),
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
        return dict(row)

    row = await run_transaction(_work)
    if row is None:
        return None
    docs = await compose_rows([row])
    return docs[0]


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
            pg_insert(moderation_messages)
            .values(
                action_id=int(action["id"]),
                chat_id=cfg.logs[0],
                message_id=log_msg_id,
                message_kind="log",
            )
            .on_conflict_do_nothing()
        )
    )


async def deactivate_all_active_bans(user_id: int) -> int:
    """Revoke every active ban for a user. Returns the number of bans revoked.

    Use this in unban and appeal-approve flows to ensure all active bans are
    cleared regardless of how many were created (guarding against duplicate
    active bans that may exist from earlier race conditions or re-ban paths).
    """
    return await db_call(
        lambda: run(
            moderation_actions.update()
            .where(
                moderation_actions.c.target_user_id == user_id,
                moderation_actions.c.action_type == "ban",
                moderation_actions.c.status == "active",
            )
            .values(status="revoked", revoked_at=utc_now())
        )
    )


async def deactivate_extra_active_bans(user_id: int, keep_ban_id: str) -> int:
    """Revoke the active bans of a user except the one that is kept.

    Called during the ban flow when an existing active ban is being updated
    to suppress any stale duplicate active bans while preserving the canonical
    record that is being reused. Returns the number of extras revoked.
    """
    return await db_call(
        lambda: run(
            moderation_actions.update()
            .where(
                moderation_actions.c.target_user_id == user_id,
                moderation_actions.c.action_type == "ban",
                moderation_actions.c.status == "active",
                moderation_actions.c.external_ref != keep_ban_id,
            )
            .values(status="revoked", revoked_at=utc_now())
        )
    )


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
                _slot_holds(review_msg_id),
            )
            .values(metadata=_drop_review_keys())
        )
    )
    return affected > 0


def _rejected_appeal_exists() -> ColumnElement[bool]:
    """Return the condition that the row carries a rejected appeal.

    The condition correlates with the decision the statement updates, so
    it can be used directly in the WHERE clause of that update.
    """
    return (
        select(moderation_appeals.c.id)
        .where(
            moderation_appeals.c.action_id == moderation_actions.c.id,
            moderation_appeals.c.status == "rejected",
        )
        .exists()
    )


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


async def release_stale_review(ban_id: str) -> bool:
    """Withdraw the open appeal of a decision and free its review slot.

    A review card that nobody answered for a long time is stale. The
    user is then allowed to appeal again, but the open appeal of the
    stale card still occupies the slot of the decision, so it has to be
    withdrawn first. Both writes land in one transaction: a withdrawn
    appeal without a free slot would leave the decision unappealable.
    """
    withdrawn = False

    async def _work(sess: AsyncSession) -> None:
        nonlocal withdrawn
        # * Both writes run on the session of this transaction: a separate
        # * session would commit the withdrawal on its own, so a failure
        # * of the slot release would leave the appeal closed and the
        # * slot still claimed.
        result = await sess.execute(
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
        withdrawn = cast("CursorResult", result).rowcount > 0
        await sess.execute(
            moderation_actions.update()
            .where(
                moderation_actions.c.external_ref == ban_id,
                moderation_actions.c.action_type == "ban",
            )
            .values(metadata=_drop_review_keys())
        )

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
    submitted_at: datetime | None = None,
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
            pg_insert(moderation_messages)
            .values(
                action_id=action,
                chat_id=cfg.logs[0],
                message_id=msg_id,
                message_kind="appeal_log",
            )
            .on_conflict_do_nothing()
        )

    await run_transaction(_work)
