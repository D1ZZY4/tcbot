# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""
Owners and admins collection helpers - manages bot staff permissions
* Handles owner and admin user management in the database
* Includes cache integration to minimize database queries
* Supports permission checks for staff-only commands
"""

from __future__ import annotations

import asyncio

from tcbot.database.cache import CACHE_MISS, _OWNER_KEY, effective_role_cache, owner_id_cache
from tcbot.database.mongos import col
from tcbot.utils.timedate_format import utc_now


# ─────────────────────── Collection Helpers ─────────────────────── #
# * Internal collection accessors for owners and admins collections

def _owners():
    return col("tc_owners")


def _admins():
    return col("tc_admins")


# ────────────────────────── Owner Queries ───────────────────────── #
# * Retrieve owner status and owner ID from database
# * All functions are async to prevent blocking on I/O operations

async def get_owner_id() -> int | None:
    """
    Get the current bot owner's user ID from cache or database

    * First checks cache for existing value to avoid DB roundtrip
    * Falls back to database query if cache miss occurs
    """
    cached = owner_id_cache.get(_OWNER_KEY)
    if cached is not CACHE_MISS:
        return cached  # type: ignore[return-value]
    doc = await _owners().find_one({}, {"_id": 0, "user_id": 1})
    result = doc["user_id"] if doc else None
    owner_id_cache.put(_OWNER_KEY, result)
    return result


async def is_owner(user_id: int) -> bool:
    """
    Check if given user ID is in the owners collection
    """
    return await _owners().find_one({"user_id": user_id}, {"_id": 1}) is not None


async def is_admin(user_id: int) -> bool:
    """
    Check if given user ID is in the admins collection
    """
    return await _admins().find_one({"user_id": user_id}, {"_id": 1}) is not None


# ──────────────────────── Combined Helpers ──────────────────────── #
# * Combined permission checks that run multiple DB queries in parallel
# * Uses asyncio.gather() to optimize latency of parallel checks

async def is_staff(user_id: int) -> bool:
    """
    True if user is owner or admin - both checks run in parallel.
    """
    owner, admin = await asyncio.gather(is_owner(user_id), is_admin(user_id))
    return owner or admin


# ───────────────────────── Owner Mutations ──────────────────────── #
# * Modify owner collection (only used for initial setup and ownership transfer)
# ! CRITICAL: These functions clear cache entries that depend on ownership

async def ensure_initial_owner(initial_id: int) -> None:
    """
    Create first owner entry if no owners exist in database
    * Used during bot initialization for first-time setup
    """
    if await _owners().count_documents({}) == 0:
        await _owners().insert_one({"user_id": initial_id})
        owner_id_cache.put(_OWNER_KEY, initial_id)


async def set_owner(user_id: int) -> None:
    """
    Replace current owner with new user ID
    ! WARNING: Deletes all existing owner entries before inserting new one
    * Clears entire effective role cache since ownership changed
    """
    await _owners().delete_many({})
    await _owners().insert_one({"user_id": user_id})
    owner_id_cache.put(_OWNER_KEY, user_id)
    # Clear the entire role cache - we don't know the old owner's user_id
    effective_role_cache.clear()


# ─────────────────────── Admin Mutations ──────────────────────── #
# * Add, remove, and manage admin users in the database
# * Automatically invalidates cache for affected users after changes

async def add_admin(user_id: int, promoted_by: int) -> None:
    """
    Add a new admin to the database if not already present
    * Uses $setOnInsert to avoid overwriting existing admin entries
    * Records promotion metadata (who promoted, when)
    TODO: Consider adding admin permissions level for granular access control
    """
    await _admins().update_one(
        {"user_id": user_id},
        {"$setOnInsert": {
            "user_id":       user_id,
            "promoted_by":   promoted_by,
            "promoted_date": utc_now(),
        }},
        upsert=True,
    )
    effective_role_cache.invalidate(user_id)


async def remove_admin(user_id: int) -> bool:
    """
    Remove an admin from the database
    * Returns True if admin was successfully removed
    * Invalidates cache for the removed admin user
    """
    r = await _admins().delete_one({"user_id": user_id})
    effective_role_cache.invalidate(user_id)
    return r.deleted_count > 0


# ────────────────────────── Admin Queries ───────────────────────── #
# * Retrieve list of all admins and admin count from database
# * Used for staff management and audit logging

async def all_admins() -> list[dict]:
    """
    Get list of all admins with their user IDs
    """
    return await _admins().find({}, {"_id": 0, "user_id": 1}).to_list(None)


async def admin_count() -> int:
    """
    Get total number of admins in the database
    """
    return await _admins().count_documents({})
