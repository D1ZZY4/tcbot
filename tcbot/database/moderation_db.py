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

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from tcbot.database.base import moderation_cases, moderation_evidence_items
from tcbot.database.base import moderation_evidence_uploads as evidence_uploads
from tcbot.database.users_cache import ensure_users
from tcbot.utils.time_and_date import utc_now

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime

    from sqlalchemy.ext.asyncio import AsyncSession

    from tcbot.database.documents import EvidenceItemDoc

# * The statuses of a case that still holds an investigation. A case in
# * one of them can carry another decision about the same subject.
OPEN_CASE_STATUSES: tuple[str, ...] = ("open", "collecting_evidence", "under_review")

# * The evidence item columns an uploader may fill. Identity and ordering
# * are owned by this module so an item cannot name another batch.
_EVIDENCE_ITEM_FIELDS: frozenset[str] = frozenset(
    {
        "media_type",
        "file_unique_id",
        "mime_type",
        "file_size_bytes",
        "duration_seconds",
        "width",
        "height",
        "file_name",
        "source_chat_id",
        "source_message_id",
        "caption_text",
        "media_group_id",
    }
)


def remaining_seconds(deadline: datetime | None, now: datetime) -> int | None:
    """Return the remaining lifetime of a decision in whole seconds.

    ``now`` is the moment the decision was created, taken once by the
    caller so ``created_at`` and the duration describe the same instant.
    A deadline that passed while the write was waiting is a bad request:
    the schema refuses an expiry that is not after creation.
    """
    if deadline is None:
        return None
    # * Compare before truncating: a deadline 0.4 s in the past truncates to
    # * 0 and would slip past the guard into a schema constraint failure.
    if deadline <= now:
        raise ValueError("a decision expiry must be in the future")
    return int((deadline - now).total_seconds())


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
    # * The case and the decision reference both accounts. A target or an
    # * actor the member cache has never seen must not fail the decision.
    await ensure_users(sess, subject_user_id, actor_user_id)
    # * Decisions about one subject can arrive from different groups at the
    # * same time, and the select-then-insert would otherwise open two cases.
    await sess.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:scope, 0))"),
        {"scope": f"case:{subject_user_id}"},
    )
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
    *,
    items: Sequence[EvidenceItemDoc] | None = None,
    expected_item_count: int | None = None,
    destination_thread_id: int | None = None,
    is_required: bool = True,
) -> int | None:
    """Archive the proof messages that actually landed and return the batch id.

    One upload owns its landed items. A gallery that lost one file is a
    ``partial`` batch, not a ``completed`` photo: the schema trigger checks
    the item count against the expected count, so the caller has to say how
    many source items it tried to send. A caller that only has the first
    message id keeps the legacy single-photo shape.
    """
    if not destination_chat_id:
        return None
    landed = [
        item for item in (items or []) if int(item.get("archive_message_id") or 0) > 0
    ]
    expected = max(len(landed), int(expected_item_count or 0))
    if not landed:
        if not proof_message_id:
            return None
        landed = [{"archive_message_id": proof_message_id, "media_type": "photo"}]
        expected = 1
    if expected < 1:
        expected = len(landed)

    upload_id = (
        (
            await sess.execute(
                pg_insert(evidence_uploads)
                .values(
                    case_id=case_id,
                    uploaded_by_user_id=uploader_user_id,
                    destination_chat_id=destination_chat_id,
                    destination_thread_id=destination_thread_id,
                    expected_item_count=expected,
                    is_required=is_required,
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
    item_values: list[dict[str, object]] = []
    for order, item in enumerate(landed):
        # * Every row carries every optional column. A multi-row insert
        # * takes its column list from the first row, so a metadata field
        # * present only on a later item would be dropped silently.
        values: dict[str, object] = {}
        for field_name in _EVIDENCE_ITEM_FIELDS:
            values[field_name] = None
        values.update(
            {key: value for key, value in item.items() if key in _EVIDENCE_ITEM_FIELDS}
        )
        values.update(
            upload_id=batch_id,
            destination_chat_id=destination_chat_id,
            archive_message_id=int(item.get("archive_message_id") or 0),
            item_order=order,
        )
        values["media_type"] = item.get("media_type") or "photo"
        item_values.append(values)
    # * One statement for the whole batch: a gallery can carry ten items,
    # * and one insert per item would add ten round trips to the ban write.
    await sess.execute(pg_insert(moderation_evidence_items).values(item_values))
    status = "completed" if len(landed) == expected else "partial"
    await sess.execute(
        evidence_uploads.update()
        .where(evidence_uploads.c.id == batch_id)
        .values(
            status=status,
            primary_message_id=int(landed[0].get("archive_message_id") or 0),
        )
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
