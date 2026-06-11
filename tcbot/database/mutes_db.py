# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Studio

"""Mute log helpers - tracks all mute events in groups."""

from __future__ import annotations

from typing import TYPE_CHECKING

from tcbot.database.mongos import col
from tcbot.utils.timedate_format import utc_now

if TYPE_CHECKING:
    from motor.motor_asyncio import AsyncIOMotorCollection

# ─────────────────────── Collection Helpers ─────────────────────── #
# * Internal collection access utilities for the mutes database


def _mutes() -> AsyncIOMotorCollection:
    return col("mutes")


# ──────────────────────────── Mutations ─────────────────────────── #
# * Functions that create or modify mute log records
# * Primarily used for audit logging of moderation actions


async def log_mute(user_id: int, chat_id: int, reason: str, admin_id: int) -> None:
    """Log a mute event to the database for audit purposes."""
    await _mutes().insert_one(
        {
            "user_id": user_id,
            "chat_id": chat_id,
            "reason": reason,
            "admin_id": admin_id,
            "timestamp": utc_now(),
        }
    )


# ─────────────────────── Per-user history ───────────────────────── #


async def user_mutes(user_id: int) -> list[dict]:
    """Return every mute record for a user, newest first."""
    return (
        await _mutes()
        .find({"user_id": user_id}, sort=[("timestamp", -1)])
        .to_list(None)
    )


async def user_mute_count(user_id: int) -> int:
    """Count every mute ever logged against the user."""
    return await _mutes().count_documents({"user_id": user_id})
