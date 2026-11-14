# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Shared write path of the community moderation decisions.

Every decision is one row in ``moderation_actions`` and every decision
belongs to a case in ``moderation_cases``. Opening the case, archiving
the proof of the decision, filing the decision, and closing the case are
one unit of work, so the shared part of that path lives here. The
per-action modules own their own reads and their own decisions.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from tcbot.database.base import moderation_cases, moderation_evidence_items
from tcbot.database.base import moderation_evidence_uploads as evidence_uploads
from tcbot.utils.time_and_date import utc_now

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

# * The statuses of a case that still holds an investigation. A case in
# * one of them can carry another decision about the same subject.
OPEN_CASE_STATUSES: tuple[str, ...] = ("open", "collecting_evidence", "under_review")


async def open_case(
    sess: AsyncSession,
    subject_user_id: int,
    actor_user_id: int,
    *,
    title: str,
    summary: str | None,
    severity: str,
    requires_evidence: bool,
) -> int:
    """Return the open case of the subject, or open one for the decision.

    A case that demands evidence is only reused by a decision that brings
    its own. An automated decision may stand on its own, so it must not
    inherit the evidence requirement of an unrelated investigation: the
    database refuses a decision that promises proof it does not carry,
    and the decision would fail instead of being filed.

    The caller owns the transaction: the case, the proof, and the
    decision have to land together, so a decision whose case cannot be
    written leaves no case behind.
    """
    stmt = select(moderation_cases.c.id).where(
        moderation_cases.c.subject_user_id == subject_user_id,
        moderation_cases.c.status.in_(OPEN_CASE_STATUSES),
    )
    if not requires_evidence:
        stmt = stmt.where(moderation_cases.c.requires_evidence.is_(False))
    existing = (await sess.execute(stmt.limit(1))).mappings().first()
    if existing is not None:
        return int(existing["id"])

    created = (
        (
            await sess.execute(
                pg_insert(moderation_cases)
                .values(
                    subject_user_id=subject_user_id,
                    case_type="rule_violation",
                    title=title,
                    summary=summary,
                    severity=severity,
                    status="open",
                    source="manual",
                    opened_by_user_id=actor_user_id,
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


async def archive_proof(
    sess: AsyncSession,
    case_id: int,
    uploader_user_id: int,
    proof_message_id: int,
    destination_chat_id: int,
) -> int | None:
    """Archive one proof message and return the batch id.

    The batch walks the lifecycle of the table: it is queued when it is
    written, the worker claims it, the archived item lands, and the batch
    closes as completed once its items are in place.
    """
    if not proof_message_id or not destination_chat_id:
        return None

    upload_id = (
        (
            await sess.execute(
                pg_insert(evidence_uploads)
                .values(
                    case_id=case_id,
                    uploaded_by_user_id=uploader_user_id,
                    destination_chat_id=destination_chat_id,
                    expected_item_count=1,
                    is_required=True,
                    status="queued",
                )
                .returning(evidence_uploads.c.id)
            )
        )
        .mappings()
        .first()
    )
    if upload_id is None:
        return None
    batch_id = int(upload_id["id"])

    await sess.execute(
        evidence_uploads.update()
        .where(evidence_uploads.c.id == batch_id)
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
        evidence_uploads.update()
        .where(evidence_uploads.c.id == batch_id)
        .values(status="completed", primary_message_id=proof_message_id)
    )
    return batch_id


async def close_case(sess: AsyncSession, case_id: int, actor_user_id: int) -> None:
    """Close the case of a decision that was filed.

    The investigation ends with its decision: a case that stays open
    forever is picked up by the next decision about the same subject, so
    the history of the community collapses into one case per user
    instead of one case per incident.

    The update only touches a case that is still open. A case that was
    closed by somebody else keeps its own closing actor and moment.
    """
    await sess.execute(
        moderation_cases.update()
        .where(
            moderation_cases.c.id == case_id,
            moderation_cases.c.status.in_(OPEN_CASE_STATUSES),
        )
        .values(
            status="resolved",
            resolved_at=utc_now(),
            closed_by_user_id=actor_user_id,
        )
    )
