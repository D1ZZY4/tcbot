# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Composition of the ban documents from the decision tables."""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, cast

from sqlalchemy import select

from tcbot.database.base import (
    moderation_actions,
    moderation_appeals,
    moderation_evidence_items,
    moderation_evidence_uploads,
    moderation_messages,
)
from tcbot.database.documents import ActionStatus, BanDoc, ScopeType
from tcbot.database.engine import db_call, fetch_all
from tcbot.database.types import BanId
from tcbot.utils.logger import get_logger

from ._shared import (
    META_APPEAL_LINK,
    META_DURATION,
    META_PREVIOUS_LOG,
    META_PREVIOUS_PROOF,
    META_REVIEW_MESSAGE,
    META_REVIEW_TIMESTAMP,
    META_UPDATE_COUNT,
)

log = get_logger(__name__)


async def _messages_for(action_ids: list[int]) -> dict[int, dict[str, int]]:
    """Return the Telegram message ids of every action, by kind."""
    if not action_ids:
        return {}
    rows = await db_call(
        lambda: fetch_all(
            select(
                moderation_messages.c.action_id,
                moderation_messages.c.message_kind,
                moderation_messages.c.message_id,
            ).where(moderation_messages.c.action_id.in_(action_ids))
        )
    )
    result: dict[int, dict[str, int]] = {}
    for row in rows:
        kind = str(row["message_kind"])
        result.setdefault(int(row["action_id"]), {})[kind] = int(row["message_id"])
    return result


async def _appeals_for(action_ids: list[int]) -> dict[int, dict[str, Any]]:
    """Return the latest appeal of every action."""
    if not action_ids:
        return {}
    rows = await db_call(
        lambda: fetch_all(
            select(
                moderation_appeals.c.action_id,
                moderation_appeals.c.status,
                moderation_appeals.c.submitted_at,
                moderation_appeals.c.resolved_at,
                moderation_appeals.c.reviewed_by_user_id,
                moderation_appeals.c.decision_note,
                moderation_appeals.c.metadata,
            )
            .where(moderation_appeals.c.action_id.in_(action_ids))
            .order_by(moderation_appeals.c.submitted_at.desc())
        )
    )
    result: dict[int, dict[str, Any]] = {}
    for row in rows:
        result.setdefault(int(row["action_id"]), dict(row))
    return result


async def _proof_ids_for(action_ids: list[int]) -> dict[int, int]:
    """Return the archived proof message id of every action."""
    if not action_ids:
        return {}
    rows = await db_call(
        lambda: fetch_all(
            select(
                moderation_actions.c.id,
                moderation_evidence_items.c.archive_message_id,
            )
            .join(
                moderation_evidence_uploads,
                moderation_evidence_uploads.c.id
                == moderation_actions.c.evidence_upload_id,
            )
            .join(
                moderation_evidence_items,
                moderation_evidence_items.c.upload_id
                == moderation_evidence_uploads.c.id,
            )
            .where(moderation_actions.c.id.in_(action_ids))
            .order_by(moderation_evidence_items.c.item_order)
        )
    )
    result: dict[int, int] = {}
    for row in rows:
        result.setdefault(int(row["id"]), int(row["archive_message_id"]))
    return result


def _review_timestamp(metadata: dict[str, Any]) -> datetime | None:
    """Return the moment the review slot was claimed.

    The slot lives in the metadata of the decision, so the timestamp is
    stored as an ISO string next to it. A value that cannot be read is
    treated as no timestamp: the review is then stale, and the user may
    submit a new appeal.
    """
    raw = metadata.get(META_REVIEW_TIMESTAMP)
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw))
    except ValueError:
        log.warning("Unreadable review timestamp in the ban metadata: %r", raw)
        return None


def compose_row(
    row: dict[str, Any],
    messages: dict[str, int],
    appeal: dict[str, Any] | None,
    proof_message_id: int | None,
) -> BanDoc:
    """Return the ban document of one decision row."""
    metadata = row.get("metadata") or {}
    if not isinstance(metadata, dict):
        metadata = {}
    action_id = int(row["id"])
    status = str(row["status"])
    return BanDoc(
        id=action_id,
        ban_id=cast("BanId", str(row["external_ref"])),
        target_user_id=row["target_user_id"],
        reason=str(row["reason"]),
        actor_user_id=row["actor_user_id"],
        proof_message_id=proof_message_id or 0,
        log_message_id=messages.get("log", 0),
        previous_proof_message_id=metadata.get(META_PREVIOUS_PROOF),
        previous_log_message_id=metadata.get(META_PREVIOUS_LOG),
        timestamp=row["created_at"],
        updated_timestamp=row.get("revoked_at") or row["created_at"],
        until_date=row.get("expires_at"),
        duration_str=metadata.get(META_DURATION),
        duration_seconds=row.get("duration_seconds"),
        is_active=status == "active",
        status=cast("ActionStatus", status),
        update_count=int(metadata.get(META_UPDATE_COUNT, 0) or 0),
        review_message_id=metadata.get(META_REVIEW_MESSAGE),
        review_timestamp=_review_timestamp(metadata),
        appeal_log_msg_id=messages.get("appeal_log"),
        appeal_submitted_at=(appeal or {}).get("submitted_at"),
        appeal_link=metadata.get(META_APPEAL_LINK),
        rejected_by_id=(appeal or {}).get("reviewed_by_user_id"),
        rejected_at=(appeal or {}).get("resolved_at"),
        case_id=int(row["case_id"]),
        evidence_upload_id=row.get("evidence_upload_id"),
        action_origin=str(row.get("action_origin") or "manual"),
        scope_type=cast("ScopeType", str(row.get("scope_type") or "community")),
        origin_chat_id=row.get("origin_chat_id"),
        metadata=metadata,
    )


async def compose_rows(rows: list[dict[str, Any]]) -> list[BanDoc]:
    """Return the ban documents of every decision row."""
    if not rows:
        return []
    action_ids = [int(row["id"]) for row in rows]
    # * The three side tables are independent reads of the same decision
    # * set, so they run concurrently and the composition waits for all
    # * of them.
    messages, appeals, proofs = await asyncio.gather(
        _messages_for(action_ids),
        _appeals_for(action_ids),
        _proof_ids_for(action_ids),
    )
    return [
        compose_row(
            row,
            messages.get(int(row["id"]), {}),
            appeals.get(int(row["id"])),
            proofs.get(int(row["id"])),
        )
        for row in rows
    ]
