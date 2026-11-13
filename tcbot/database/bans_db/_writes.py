# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Write helpers over the community ban decisions."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

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
)

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.sql.elements import ColumnElement

log = get_logger(__name__)


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

    The slot lives in the metadata of the decision: the update matches
    only when no review is stored, so two concurrent appeal submissions
    for the same ban cannot both claim the slot.
    """
    action = await action_by_ref(ban_id)
    if action is None:
        return False
    metadata = dict(action.get("metadata") or {})
    if metadata.get(META_REVIEW_MESSAGE):
        return False
    metadata[META_REVIEW_MESSAGE] = msg_id
    metadata[META_REVIEW_TIMESTAMP] = utc_now().isoformat()
    affected = await db_call(
        lambda: run(
            moderation_actions.update()
            .where(moderation_actions.c.id == int(action["id"]))
            .values(metadata=metadata)
        )
    )
    return affected > 0


async def clear_review(ban_id: str) -> None:
    """Release the review slot, allowing a new appeal to be submitted.

    Called after an appeal is rejected so the banned user is not permanently
    locked out from submitting a second appeal.
    """
    action = await action_by_ref(ban_id)
    if action is None:
        return
    metadata = dict(action.get("metadata") or {})
    metadata.pop(META_REVIEW_MESSAGE, None)
    metadata.pop(META_REVIEW_TIMESTAMP, None)
    await db_call(
        lambda: run(
            moderation_actions.update()
            .where(moderation_actions.c.id == int(action["id"]))
            .values(metadata=metadata)
        )
    )


async def claim_appeal_decision(ban_id: str, review_msg_id: int) -> bool:
    """Atomically claim one appeal decision; return True when claimed.

    The claim consumes the review slot. A claim that ends without a
    decision must hand the slot back with :func:`restore_review`.
    """
    action = await action_by_ref(ban_id)
    if action is None:
        return False
    metadata = dict(action.get("metadata") or {})
    if metadata.get(META_REVIEW_MESSAGE) != review_msg_id:
        return False
    if str(action.get("status")) != "active":
        return False
    metadata.pop(META_REVIEW_MESSAGE, None)
    metadata.pop(META_REVIEW_TIMESTAMP, None)
    affected = await db_call(
        lambda: run(
            moderation_actions.update()
            .where(
                moderation_actions.c.id == int(action["id"]),
                moderation_actions.c.status == "active",
            )
            .values(metadata=metadata)
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
    action = await action_by_ref(ban_id)
    if action is None:
        return False
    metadata = dict(action.get("metadata") or {})
    if metadata.get(META_REVIEW_MESSAGE):
        return False
    if str(action.get("status")) != "active":
        return False
    metadata[META_REVIEW_MESSAGE] = review_msg_id
    metadata[META_REVIEW_TIMESTAMP] = (review_timestamp or utc_now()).isoformat()
    affected = await db_call(
        lambda: run(
            moderation_actions.update()
            .where(
                moderation_actions.c.id == int(action["id"]),
                moderation_actions.c.status == "active",
                # * A rejected appeal is a decision: its review card must
                # * not come back, or a second reviewer could decide it
                # * again.
                ~_rejected_appeal_exists(),
            )
            .values(metadata=metadata)
        )
    )
    return affected > 0


async def set_rejected_by(ban_id: str, admin_id: int, admin_name: str) -> None:
    """Persist the rejector identity and rejection timestamp on a ban document.

    Called on appeal reject so the audit trail is preserved even if the log
    message is later deleted or the log channel is unavailable.
    """
    action = await action_by_ref(ban_id)
    if action is None:
        return
    await db_call(
        lambda: run(
            moderation_appeals.update()
            .where(
                moderation_appeals.c.action_id == int(action["id"]),
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


async def set_appeal_log_msg(
    ban_id: str,
    msg_id: int,
    submitted_at: datetime | None = None,
    appeal_link: str = "",
) -> None:
    """Attach appeal-related metadata to a ban record."""
    action = await action_by_ref(ban_id)
    if action is None:
        return
    metadata = dict(action.get("metadata") or {})
    if appeal_link:
        metadata[META_APPEAL_LINK] = appeal_link
    await db_call(
        lambda: run(
            moderation_actions.update()
            .where(moderation_actions.c.id == int(action["id"]))
            .values(metadata=metadata)
        )
    )
    await db_call(
        lambda: run(
            pg_insert(moderation_messages)
            .values(
                action_id=int(action["id"]),
                chat_id=cfg.logs[0],
                message_id=msg_id,
                message_kind="appeal_log",
            )
            .on_conflict_do_nothing()
        )
    )
