# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""
Federated groups and pending joins collection helpers
* Manages all connected groups in the federation
* Tracks pending join requests from groups wanting to connect
* Maintains cache for active group status to reduce DB queries
"""

from __future__ import annotations

from typing import cast

from tcbot.database.cache import (
    _ALL_GROUPS_KEY,
    CACHE_MISS,
    active_groups_cache,
    connected_cache,
)
from tcbot.database.documents import GroupDoc, PendingGroupDoc
from tcbot.database.mongos import col
from tcbot.utils.timedate_format import utc_now

# ─────────────────────── Collection Helpers ─────────────────────── #
# * Internal collection access utilities for groups database


def _groups():
    """Get the federated_groups collection reference from MongoDB"""
    return col("federated_groups")


def _pending():
    """Get the pending_joins collection reference from MongoDB"""
    return col("pending_joins")


# ──────────────────── Group Queries & Mutations ─────────────────── #
# * Functions to manage active connected groups in the federation
# * Includes caching to minimize database roundtrips
# ! CRITICAL: Cache invalidation is crucial here - always clear caches on changes


async def get_group(chat_id: int) -> GroupDoc | None:
    """
    Get the full group record for a specific chat ID
    * Returns None if the group is not in the federated_groups collection
    """
    return await _groups().find_one({"chat_id": chat_id})


async def is_connected(chat_id: int) -> bool:
    """
    Check if a group is currently active and connected to the federation
    * First checks cache to avoid DB queries - returns cached value if available
    * Queries database only on cache miss and updates the cache
    * Caches boolean result to optimize repeated checks
    """
    cached = connected_cache.get(chat_id)
    if cached is not CACHE_MISS:
        return cast(bool, cached)
    result = (
        await _groups().find_one({"chat_id": chat_id, "is_active": True}, {"_id": 1})
        is not None
    )
    connected_cache.put(chat_id, result)
    return result


async def add_group(chat_id: int, title: str, added_by: int) -> None:
    """
    Add or update a group in the federated_groups collection
    * Uses upsert to create new records or update existing ones
    * Updates connected_cache and clears active_groups_cache
    ! CRITICAL: Always clears cache after modifying group status
    """
    await _groups().update_one(
        {"chat_id": chat_id},
        {
            "$set": {
                "chat_id": chat_id,
                "title": title,
                "added_by": added_by,
                "added_date": utc_now(),
                "is_active": True,
            }
        },
        upsert=True,
    )
    connected_cache.put(chat_id, True)
    active_groups_cache.clear()


async def deactivate_group(chat_id: int) -> bool:
    """
    Mark a group as inactive (disconnect from federation)
    * Updates the database and invalidates relevant caches
    * Returns True if the group was found and updated
    """
    r = await _groups().update_one({"chat_id": chat_id}, {"$set": {"is_active": False}})
    connected_cache.put(chat_id, False)
    active_groups_cache.clear()
    return r.matched_count > 0


async def active_groups() -> list[GroupDoc]:
    """
    Get all currently active and connected groups
    * Caches the full list to avoid repeated full-collection queries
    * Cache is cleared whenever groups are added or removed
    """
    cached = active_groups_cache.get(_ALL_GROUPS_KEY)
    if cached is not CACHE_MISS:
        return cast(list[GroupDoc], cached)
    result: list[GroupDoc] = await _groups().find({"is_active": True}).to_list(None)
    active_groups_cache.put(_ALL_GROUPS_KEY, result)
    return result


async def active_group_count() -> int:
    """
    Count the number of currently active connected groups
    * Uses efficient count_documents for fast retrieval
    """
    return await _groups().count_documents({"is_active": True})


# ──────────────────── Pending Joins Management ──────────────────── #
# * Functions to manage groups waiting to be approved into the federation
# * Tracks join requests with all necessary metadata


async def add_pending(chat_id: int, title: str, owner_id: int, message_id: int) -> None:
    """
    Add or update a pending join request from a group
    * Stores group info, owner ID, and the message ID of the join request
    * Uses upsert to update existing requests if submitted again
    """
    await _pending().update_one(
        {"chat_id": chat_id},
        {
            "$set": {
                "chat_id": chat_id,
                "title": title,
                "owner_id": owner_id,
                "message_id": message_id,
                "added_date": utc_now(),
            }
        },
        upsert=True,
    )


async def get_pending(chat_id: int) -> PendingGroupDoc | None:
    """
    Get a pending join request by chat ID
    * Returns None if there's no pending request for that chat
    """
    return await _pending().find_one({"chat_id": chat_id})


async def remove_pending(chat_id: int) -> None:
    """
    Remove a pending join request after it's approved or rejected
    * Deletes the document from the pending_joins collection
    """
    await _pending().delete_one({"chat_id": chat_id})
