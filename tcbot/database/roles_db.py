# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""Role management system - handles custom staff roles like developer and tester."""

from __future__ import annotations

import asyncio
from typing import cast

from tcbot.database.admins_db import is_admin, is_owner
from tcbot.database.cache import CACHE_MISS, effective_role_cache
from tcbot.database.documents import RoleDoc, RoleRefDoc
from tcbot.database.mongos import col
from tcbot.utils.timedate_format import utc_now

VALID_ROLES: frozenset[str] = frozenset({"developer", "tester"})

ROLE_RANK: dict[str, int] = {
    "founder": 4,
    "admin": 3,
    "developer": 2,
    "tester": 1,
}

ROLE_LABEL: dict[str, str] = {
    "founder": "Founder",
    "admin": "Admin",
    "developer": "Developer",
    "tester": "Tester",
}


def role_rank(role: str | None) -> int:
    """Convert a role string to its numeric rank value for comparison."""
    return ROLE_RANK.get(role or "", 0)


def _col():
    return col("tc_roles")


# ──────────────────────────── Role CRUD ─────────────────────────── #
# * Create, read, update, delete operations for role records
# * All write operations automatically invalidate the user's cache


async def set_role(user_id: int, role: str, assigned_by: int) -> None:
    """Assign a custom role to a user."""
    await _col().update_one(
        {"user_id": user_id},
        {
            "$set": {
                "user_id": user_id,
                "role": role,
                "assigned_by": assigned_by,
                "assigned_at": utc_now(),
            }
        },
        upsert=True,
    )
    effective_role_cache.invalidate(user_id)


async def remove_role(user_id: int) -> bool:
    """Remove a user's custom role from the database."""
    r = await _col().delete_one({"user_id": user_id})
    effective_role_cache.invalidate(user_id)
    return r.deleted_count > 0


async def get_role(user_id: int) -> str | None:
    """Get a user's custom role from the database only."""
    doc = await _col().find_one({"user_id": user_id}, {"role": 1})
    return doc["role"] if doc else None


async def all_by_role(role: str) -> list[RoleRefDoc]:
    """Get all users with a specific custom role."""
    return await _col().find({"role": role}, {"_id": 0, "user_id": 1}).to_list(None)


async def all_roles() -> list[RoleDoc]:
    """Get all custom role assignments in the database."""
    return await _col().find({}).to_list(None)


# ───────────────────────── Role Resolution ──────────────────────── #
# * Functions to resolve effective permissions and role hierarchy
# * Core permission system that powers all staff-only command checks


async def can_act_on(executor_id: int, target_id: int) -> bool:
    """Check if an executor can perform moderation actions on a target."""
    executor_role, target_role = await asyncio.gather(
        get_effective_role(executor_id),
        get_effective_role(target_id),
    )
    return role_rank(executor_role) > role_rank(target_role)


async def get_effective_role(user_id: int) -> str | None:
    """Resolve a user's full effective role including owner/admin status."""
    cached = effective_role_cache.get(user_id)
    if cached is not CACHE_MISS:
        return cast(str | None, cached)

    owner, admin, role = await asyncio.gather(
        is_owner(user_id),
        is_admin(user_id),
        get_role(user_id),
    )
    result: str | None = "founder" if owner else "admin" if admin else role
    effective_role_cache.put(user_id, result)
    return result
