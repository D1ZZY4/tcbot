# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Studio

"""Kick log helpers - tracks all kick events in groups."""

from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorCollection

from tcbot.database.mongos import col
from tcbot.utils.timedate_format import utc_now

# ─────────────────────── Collection Helpers ─────────────────────── #
# * Internal collection access utilities for the kicks database


def _kicks() -> AsyncIOMotorCollection:
    return col("kicks")


# ──────────────────────────── Mutations ─────────────────────────── #
# * Functions that create or modify kick log records
# * Used exclusively for audit logging of moderation actions


async def log_kick(user_id: int, chat_id: int, reason: str, admin_id: int) -> None:
    """Log a kick event to the database for audit purposes."""
    await _kicks().insert_one(
        {
            "user_id": user_id,
            "chat_id": chat_id,
            "reason": reason,
            "admin_id": admin_id,
            "timestamp": utc_now(),
        }
    )


# ─────────────────────── Per-user history ───────────────────────── #


async def user_kicks(user_id: int) -> list[dict]:
    """Return every kick record for a user, newest first."""
    return (
        await _kicks()
        .find({"user_id": user_id}, sort=[("timestamp", -1)])
        .to_list(None)
    )


async def user_kick_count(user_id: int) -> int:
    """Count every kick ever logged against the user."""
    return await _kicks().count_documents({"user_id": user_id})
