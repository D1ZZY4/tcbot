# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""
Bans collection helpers - manages all ban-related database operations
* Handles creation, updates, deactivation, and retrieval of user bans
* Stores all ban metadata including reason, admin info, timestamps, and review data
"""

from __future__ import annotations

from datetime import datetime

from tcbot.database.documents import BanDoc
from tcbot.database.mongos import col, make_short_id
from tcbot.utils.timedate_format import utc_now

# ─────────────────────── Collection Helpers ─────────────────────── #
# * Internal collection access and ID generation utilities
# * These are only used within this module for database interactions


def _bans():
    """Get the bans collection reference from MongoDB"""
    return col("bans")


def make_ban_id() -> str:
    """Generate a unique short ID for new ban records"""
    return make_short_id()


# ──────────────────────────── Retrieval ─────────────────────────── #
# * Functions to fetch ban data from the database
# * Includes both active ban queries and full ban record lookups


async def get_active_ban(user_id: int) -> BanDoc | None:
    """
    Get the currently active ban for a specific user
    * Returns None if the user has no active bans
    * Queries only bans marked with 'is_active': True
    """
    return await _bans().find_one(
        {"banned_user_id": user_id, "is_active": True},
        sort=[("timestamp", -1), ("ban_id", -1)],
    )


async def get_ban(ban_id: str) -> BanDoc | None:
    """
    Get any ban record by its unique ban_id
    * Returns the full ban document including history and metadata
    * Works for both active and inactive bans
    """
    return await _bans().find_one({"ban_id": ban_id})


# ──────────────────────────── Mutations ─────────────────────────── #
# * Functions that modify ban records in the database
# * Includes creation, updates, deactivation, and metadata changes
# ! CRITICAL: These functions modify persistent data - always validate inputs


async def create_ban(
    target_id: int,
    reason: str,
    admin_id: int,
    proof_msg_id: int,
    log_msg_id: int,
    ban_id: str | None = None,
) -> BanDoc:
    """
    Create a new ban record in the database
    * Generates a unique ban_id if not provided
    * Initializes all metadata fields with default values
    * Returns the complete created ban document
    """
    if ban_id is None:
        ban_id = make_ban_id()
    doc = {
        "ban_id": ban_id,
        "banned_user_id": target_id,
        "reason": reason,
        "admin_user_id": admin_id,
        "proof_message_id": proof_msg_id,
        "log_message_id": log_msg_id,
        "previous_proof_message_id": None,
        "previous_log_message_id": None,
        "timestamp": utc_now(),
        "updated_timestamp": None,
        "is_active": True,
        "update_count": 0,
        "review_message_id": None,
        "review_timestamp": None,
    }
    await _bans().insert_one(doc)
    return doc


async def update_ban(
    ban_id: str,
    reason: str,
    admin_id: int,
    new_proof_id: int,
    new_log_id: int = 0,
    old_proof_id: int = 0,
    old_log_id: int = 0,
) -> BanDoc | None:
    """
    Update an existing ban record with new information
    * Preserves previous proof and log message IDs for audit history
    * Increments update_count to track number of modifications
    * Returns the updated document if found
    """
    return await _bans().find_one_and_update(
        {"ban_id": ban_id},
        {
            "$set": {
                "reason": reason,
                "admin_user_id": admin_id,
                "proof_message_id": new_proof_id,
                "log_message_id": new_log_id,
                "previous_proof_message_id": old_proof_id,
                "previous_log_message_id": old_log_id,
                "updated_timestamp": utc_now(),
            },
            "$inc": {"update_count": 1},
        },
        return_document=True,
    )


async def set_log_message_id(ban_id: str, log_msg_id: int) -> None:
    """
    Update only the log message ID for an existing ban
    * Used when the log message needs to be recreated or moved
    """
    await _bans().update_one(
        {"ban_id": ban_id},
        {"$set": {"log_message_id": log_msg_id}},
    )


async def deactivate_ban(ban_id: str) -> bool:
    """
    Mark a ban as inactive (user is unbanned)
    * Returns True if the ban was found and updated
    * This is the primary way to remove active bans
    """
    r = await _bans().update_one({"ban_id": ban_id}, {"$set": {"is_active": False}})
    return r.modified_count > 0


async def set_review(ban_id: str, msg_id: int) -> None:
    """
    Attach a review message ID to a ban record
    * Used when the ban is being reviewed by admins
    * Sets the review timestamp automatically
    """
    await _bans().update_one(
        {"ban_id": ban_id},
        {"$set": {"review_message_id": msg_id, "review_timestamp": utc_now()}},
    )


async def set_appeal_log_msg(
    ban_id: str,
    msg_id: int,
    submitted_at: datetime | None = None,
    appeal_link: str = "",
) -> None:
    """
    Attach appeal-related metadata to a ban record
    * Stores the appeal log message ID and submission timestamp
    * Can include a direct link to the appeal thread
    """
    await _bans().update_one(
        {"ban_id": ban_id},
        {
            "$set": {
                "appeal_log_msg_id": msg_id,
                "appeal_submitted_at": submitted_at or utc_now(),
                "appeal_link": appeal_link,
            }
        },
    )


# ─────────────────────────── Statistics ─────────────────────────── #
# * Aggregation and counting functions for ban statistics
# * Optimized queries for performance-critical operations


async def active_ban_count() -> int:
    """
    Count the total number of currently active bans
    * Uses MongoDB's efficient count_documents for fast retrieval
    """
    return await _bans().count_documents({"is_active": True})


async def active_bans() -> list[BanDoc]:
    """
    Get all active ban records in the database
    * Returns full documents for all currently banned users
    """
    return (
        await _bans()
        .find({"is_active": True}, sort=[("timestamp", -1), ("ban_id", -1)])
        .to_list(None)
    )


async def active_ban_user_ids() -> list[int]:
    """
    Return only the user IDs of all active bans (projection-only, fastest path)
    * Uses projection to fetch only the required field, minimizing data transfer
    * This is the most efficient way to get a list of banned user IDs
    """
    docs = (
        await _bans()
        .find(
            {"is_active": True},
            {"_id": 0, "banned_user_id": 1},
            sort=[("timestamp", -1), ("ban_id", -1)],
        )
        .to_list(None)
    )
    return [doc["banned_user_id"] for doc in docs]
