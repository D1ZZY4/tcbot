# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""Owners and admins collection helpers – manages bot staff permissions."""

from __future__ import annotations

import asyncio
from typing import cast

from tcbot.database.cache import (
    _OWNER_KEY,
    CACHE_MISS,
    effective_role_cache,
    owner_id_cache,
)
from tcbot.database.documents import AdminDoc
from tcbot.database.mongos import col
from tcbot.utils.timedate_format import utc_now

# ─────────────────────── Collection Helpers ─────────────────────── #


def _owners():
    return col("tc_owners")


def _admins():
    return col("tc_admins")


# ────────────────────────── Owner Queries ───────────────────────── #


async def get_owner_id() -> int | None:
    """Return the current owner's user ID (cached)."""
    cached = owner_id_cache.get(_OWNER_KEY)
    if cached is not CACHE_MISS:
        return cast(int | None, cached)
    doc: AdminDoc | None = await _owners().find_one({}, {"_id": 0, "user_id": 1})
    result = doc["user_id"] if doc else None
    owner_id_cache.put(_OWNER_KEY, result)
    return result


async def is_owner(user_id: int) -> bool:
    """Return True if user_id belongs to the bot owner."""
    return await _owners().find_one({"user_id": user_id}, {"_id": 1}) is not None


async def is_admin(user_id: int) -> bool:
    """Return True if user_id is a registered admin."""
    return await _admins().find_one({"user_id": user_id}, {"_id": 1}) is not None


# ──────────────────────── Combined Helpers ──────────────────────── #
# * Both checks run in parallel via asyncio.gather


async def is_staff(user_id: int) -> bool:
    """Return True if user_id is owner or admin."""
    owner, admin = await asyncio.gather(is_owner(user_id), is_admin(user_id))
    return owner or admin


# ───────────────────────── Owner Mutations ──────────────────────── #
# ! CRITICAL: These functions clear cache entries that depend on ownership


async def ensure_initial_owner(initial_id: int) -> None:
    """Create the first owner entry if the owners collection is empty."""
    if await _owners().count_documents({}) == 0:
        await _owners().insert_one({"user_id": initial_id})
        owner_id_cache.put(_OWNER_KEY, initial_id)


async def set_owner(user_id: int) -> None:
    """Replace the current owner with user_id; clears the role cache."""
    await _owners().delete_many({})
    await _owners().insert_one({"user_id": user_id})
    owner_id_cache.put(_OWNER_KEY, user_id)
    # * Clear the full role cache – the old owner's ID is unknown
    effective_role_cache.clear()


# ───────────────────────── Admin Mutations ──────────────────────── #
# * Cache is invalidated for affected users after every write


async def add_admin(user_id: int, promoted_by: int) -> None:
    """Add a new admin via upsert; no-op if already present."""
    # TODO: Consider adding a permissions-level field for granular access control
    await _admins().update_one(
        {"user_id": user_id},
        {
            "$setOnInsert": {
                "user_id": user_id,
                "promoted_by": promoted_by,
                "promoted_date": utc_now(),
            }
        },
        upsert=True,
    )
    effective_role_cache.invalidate(user_id)


async def remove_admin(user_id: int) -> bool:
    """Remove an admin; return True if the entry was deleted."""
    r = await _admins().delete_one({"user_id": user_id})
    effective_role_cache.invalidate(user_id)
    return r.deleted_count > 0


# ────────────────────────── Admin Queries ───────────────────────── #


async def all_admins() -> list[AdminDoc]:
    """Return all admin documents."""
    return await _admins().find({}, {"_id": 0, "user_id": 1}).to_list(None)


async def admin_count() -> int:
    """Return the total count of registered admins."""
    return await _admins().count_documents({})
