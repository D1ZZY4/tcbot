# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Kick log helpers - tracks all kick events in groups."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from tcbot.database.documents import KickDoc
from tcbot.database.mongos import col, db_call
from tcbot.database.types import ChatId, UserId
from tcbot.utils.time_and_date import utc_now

if TYPE_CHECKING:
    from motor.motor_asyncio import AsyncIOMotorCollection

log = logging.getLogger(__name__)

# ─────────────────────── Collection Helpers ─────────────────────── #
# * Internal collection access utilities for the kicks database


def _kicks() -> AsyncIOMotorCollection:
    return col("kicks")


# ──────────────────────────── Mutations ─────────────────────────── #
# * Functions that create or modify kick log records
# * Used exclusively for audit logging of moderation actions


async def log_kick(user_id: int, chat_id: int, reason: str, admin_id: int) -> None:
    """Log a kick event to the database for audit purposes."""
    doc: KickDoc = {
        "user_id": UserId(user_id),
        "chat_id": ChatId(chat_id),
        "reason": reason,
        "admin_id": UserId(admin_id),
        "timestamp": utc_now(),
    }
    await db_call(_kicks().insert_one(doc))


# ─────────────────────── Per-user history ───────────────────────── #


async def user_kicks(
    user_id: int, *, skip: int = 0, limit: int | None = None
) -> list[KickDoc]:
    """Return every kick record for a user, newest first.

    ``limit=None`` returns the full list (backwards compatible).
    """
    cursor = (
        _kicks()
        .find({"user_id": user_id}, {"_id": 0}, sort=[("timestamp", -1)])
        .skip(max(0, skip))
    )
    if limit is not None:
        cursor = cursor.limit(max(1, limit))
    return await db_call(cursor.to_list(limit))


async def user_kick_count(user_id: int) -> int:
    """Count every kick ever logged against the user."""
    return await db_call(_kicks().count_documents({"user_id": user_id}))


async def migrate_records(old_chat_id: int, new_chat_id: int) -> bool:
    """Repoint every kick record from ``old_chat_id`` to ``new_chat_id``.

    Called on basic-group to supergroup migration so /check kick history
    does not split across the legacy chat. Kick rows carry no unique
    per-pair state, so a plain repoint is safe. Cancellation propagates.
    """
    try:
        res = await db_call(
            _kicks().update_many(
                {"chat_id": old_chat_id},
                {"$set": {"chat_id": new_chat_id}},
            )
        )
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception(
            "kicks_db.migrate_records (%d -> %d) failed", old_chat_id, new_chat_id
        )
        return False
    return res.matched_count > 0
