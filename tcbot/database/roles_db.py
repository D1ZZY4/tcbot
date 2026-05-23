# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""
Role management system - handles custom staff roles like developer and tester
* Manages the tc_roles collection for non-admin staff permissions
* Resolves effective role hierarchy: founder > admin > developer > tester
* Includes caching to minimize database roundtrips for permission checks
"""

from __future__ import annotations

import asyncio

from tcbot.database.admins_db import is_admin, is_owner
from tcbot.database.cache import CACHE_MISS, effective_role_cache
from tcbot.database.mongos import col
from tcbot.utils.timedate_format import utc_now

VALID_ROLES: frozenset[str] = frozenset({"developer", "tester"})

ROLE_RANK: dict[str, int] = {
    "founder":   4,
    "admin":     3,
    "developer": 2,
    "tester":    1,
}

ROLE_LABEL: dict[str, str] = {
    "founder":   "Founder",
    "admin":     "Admin",
    "developer": "Developer",
    "tester":    "Tester",
}


def role_rank(role: str | None) -> int:
    """
    Convert a role string to its numeric rank value for comparison
    * Returns 0 for unknown or no role (lowest priority)
    * Higher numbers mean higher permissions
    """
    return ROLE_RANK.get(role or "", 0)


def _col():
    """Get the tc_roles collection reference from MongoDB"""
    return col("tc_roles")


# ──────────────────────────── Role CRUD ─────────────────────────── #
# * Create, read, update, delete operations for role records
# * All write operations automatically invalidate the user's cache

async def set_role(user_id: int, role: str, assigned_by: int) -> None:
    """
    Assign a custom role to a user
    * Uses upsert to create new records or update existing ones
    * Automatically invalidates the user's effective role cache
    * Records who assigned the role and when
    """
    await _col().update_one(
        {"user_id": user_id},
        {"$set": {
            "user_id":     user_id,
            "role":        role,
            "assigned_by": assigned_by,
            "assigned_at": utc_now(),
        }},
        upsert=True,
    )
    effective_role_cache.invalidate(user_id)


async def remove_role(user_id: int) -> bool:
    """
    Remove a user's custom role from the database
    * Returns True if the role was successfully removed
    * Invalidates the user's cache after deletion
    """
    r = await _col().delete_one({"user_id": user_id})
    effective_role_cache.invalidate(user_id)
    return r.deleted_count > 0


async def get_role(user_id: int) -> str | None:
    """
    Get a user's custom role from the database only
    * Returns None if the user has no custom role assigned
    * This only fetches the tc_roles collection entry, not effective role
    """
    doc = await _col().find_one({"user_id": user_id}, {"role": 1})
    return doc["role"] if doc else None


async def all_by_role(role: str) -> list[dict]:
    """
    Get all users with a specific custom role
    * Returns only user IDs for efficient data transfer
    """
    return await _col().find({"role": role}, {"_id": 0, "user_id": 1}).to_list(None)


async def all_roles() -> list[dict]:
    """
    Get all custom role assignments in the database
    * Returns full documents for all users with custom roles
    """
    return await _col().find({}).to_list(None)


# ───────────────────────── Role Resolution ──────────────────────── #
# * Functions to resolve effective permissions and role hierarchy
# * Core permission system that powers all staff-only command checks

async def can_act_on(executor_id: int, target_id: int) -> bool:
    """
    Check if an executor can perform moderation actions on a target
    * Returns True only if executor's role rank is strictly higher than target's
    * Runs both role lookups in parallel with asyncio.gather() for speed
    * This is the primary permission check for all moderation commands
    """
    executor_role, target_role = await asyncio.gather(
        get_effective_role(executor_id),
        get_effective_role(target_id),
    )
    return role_rank(executor_role) > role_rank(target_role)


async def get_effective_role(user_id: int) -> str | None:
    """
    Resolve a user's full effective role including owner/admin status
    * Hierarchy: founder (owner) > admin > developer > tester > None
    * Caches result for 60 seconds to eliminate repeated DB queries
    * Cache is invalidated automatically whenever roles are modified
    * Combines owner, admin, and custom role checks in parallel
    """
    cached = effective_role_cache.get(user_id)
    if cached is not CACHE_MISS:
        return cached  # type: ignore[return-value]

    owner, admin, role = await asyncio.gather(
        is_owner(user_id),
        is_admin(user_id),
        get_role(user_id),
    )
    result: str | None = "founder" if owner else "admin" if admin else role
    effective_role_cache.put(user_id, result)
    return result
