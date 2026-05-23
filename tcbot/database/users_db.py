# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""
Member cache collection - stores user profile information
* Caches first_name, last_name, username for all interacting users
* Maintains last_updated timestamps to keep profile data fresh
"""

from __future__ import annotations

from tcbot.database.mongos import col
from tcbot.utils.timedate_format import utc_now

# ─────────────────────── Collection Helpers ─────────────────────── #
# * Internal collection access utilities for the member cache database


def _users():
    """Get the member_cache collection reference from MongoDB"""
    return col("member_cache")


# ──────────────────────────── Mutations ─────────────────────────── #
# * Functions that update or create user cache records
# * Keeps profile data fresh for all interacting users
# ! CRITICAL: This is the primary way to update cached user information


async def upsert_user(
    user_id: int,
    username: str | None,
    first_name: str,
    last_name: str | None = None,
) -> None:
    """
    Update or insert a user's profile information into the cache
    * Uses upsert to create new records or update existing ones
    * Sets last_updated every time to track freshness
    * commit_date is only set once when the record is first created
    """
    now = utc_now()
    await _users().update_one(
        {"user_id": user_id},
        {
            "$set": {
                "user_id": user_id,
                "username": username,
                "first_name": first_name,
                "last_name": last_name,
                "last_updated": now,
            },
            "$setOnInsert": {
                "commit_date": now,
            },
        },
        upsert=True,
    )


# ─────────────────────── Queries & Retrieval ────────────────────── #
# * Functions to fetch user cache data from the database
# * Includes profile lookups and statistics


async def get_user(user_id: int) -> dict | None:
    """
    Get the full cached profile for a specific user
    * Returns None if the user has never interacted with the bot
    """
    return await _users().find_one({"user_id": user_id})


async def get_first_name(user_id: int, fallback: str = "") -> str:
    """Return cached first_name or fallback string.
    * Optimized query that only fetches the first_name field
    * Used for quick mentions or displays where only the name is needed
    """
    doc = await _users().find_one({"user_id": user_id}, {"first_name": 1})
    if doc:
        return doc.get("first_name") or fallback
    return fallback


async def total_users() -> int:
    """
    Get the total number of unique users in the cache
    * Counts all documents in the member_cache collection
    """
    return await _users().count_documents({})
