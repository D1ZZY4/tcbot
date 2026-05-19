# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""
Warnings collection helpers - manages user warning records in groups
* Tracks all warnings issued to users by admins in specific chats
* Stores warning metadata including reason, admin, and timestamp
"""

from __future__ import annotations

from datetime import datetime, timezone

from tcbot.database.mongos import col


# ─────────────────────── Collection Helpers ─────────────────────── #
# * Internal collection access utilities for the warns database

def _warns():
    """Get the warns collection reference from MongoDB"""
    return col("warns")


# ──────────────────────────── Mutations ─────────────────────────── #
# * Functions that modify warning records in the database
# * Includes adding, removing, and clearing warnings
# ! CRITICAL: These functions modify per-chat warning counts

async def add_warn(user_id: int, reason: str, admin_id: int, chat_id: int) -> int:
    """
    Add a new warning to a user in a specific chat
    * Creates a new warn document with all required metadata
    * Returns the updated warning count for that user in the chat
    * Timestamps are stored in UTC for consistency
    """
    c = _warns()
    await c.insert_one({
        "user_id": user_id,
        "reason": reason,
        "admin_id": admin_id,
        "chat_id": chat_id,
        "timestamp": datetime.now(timezone.utc),
    })
    return await c.count_documents({"user_id": user_id, "chat_id": chat_id})


# ─────────────────────── Queries & Retrieval ────────────────────── #
# * Functions to fetch warning data from the database
# * Includes counting, listing, and retrieving user warnings

async def warn_count(user_id: int, chat_id: int) -> int:
    """
    Get the current number of warnings for a user in a specific chat
    * Uses efficient count_documents to get the total quickly
    """
    return await _warns().count_documents({"user_id": user_id, "chat_id": chat_id})


async def clear_warns(user_id: int, chat_id: int) -> int:
    """
    Remove ALL warnings for a user in a specific chat
    * Returns the number of warning documents that were deleted
    * Use this to reset a user's warning count completely
    """
    r = await _warns().delete_many({"user_id": user_id, "chat_id": chat_id})
    return r.deleted_count


async def get_warns(user_id: int, chat_id: int) -> list[dict]:
    """
    Return all warn documents for a user in a chat, oldest first.
    * Sorts results by timestamp ascending to maintain chronological order
    * Returns full warning documents including all metadata
    """
    cursor = _warns().find(
        {"user_id": user_id, "chat_id": chat_id},
        sort=[("timestamp", 1)],
    )
    return await cursor.to_list(length=None)


async def remove_last_warn(user_id: int, chat_id: int) -> bool:
    """
    Delete the most recent warn document. Returns True if one was removed.
    * Finds the latest warning by sorting timestamps in descending order
    * Only removes a single warning - use clear_warns() to remove all
    """
    doc = await _warns().find_one(
        {"user_id": user_id, "chat_id": chat_id},
        sort=[("timestamp", -1)],
    )
    if not doc:
        return False
    await _warns().delete_one({"_id": doc["_id"]})
    return True
