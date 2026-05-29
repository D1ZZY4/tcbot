# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""User cache plus federation staff: owners, admins, developer/tester roles, and effective-role resolution."""

from __future__ import annotations

import asyncio
from typing import cast

from pymongo.errors import DuplicateKeyError

from tcbot.database.cache import (
    _OWNER_KEY,
    CACHE_MISS,
    effective_role_cache,
    owner_id_cache,
)
from tcbot.database.documents import AdminDoc, RoleDoc, RoleRefDoc, UserDoc
from tcbot.database.mongos import col
from tcbot.utils.timedate_format import utc_now

# ────────────────────── Role hierarchy tables ───────────────────── #
# * Numeric ranks compare executor vs target; labels render to humans.

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


# ─────────────────────── Collection helpers ─────────────────────── #


def _users():
    return col("member_cache")


def _owners():
    return col("tc_owners")


def _admins():
    return col("tc_admins")


def _roles():
    return col("tc_roles")


# ───────────────────── Member cache mutations ───────────────────── #


async def upsert_user(
    user_id: int,
    username: str | None,
    first_name: str,
    last_name: str | None = None,
) -> None:
    """Update or insert a user's profile information into the cache."""
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


# ───────────────────── Member cache queries ─────────────────────── #


async def get_user(user_id: int) -> UserDoc | None:
    """Get the full cached profile for a specific user."""
    return await _users().find_one({"user_id": user_id})


async def get_user_mention_data(user_id: int) -> tuple[str, str | None]:
    """Return (first_name, username) for mention formatting.

    Optimized query that fetches only the fields needed for mentions,
    avoiding full document retrieval.
    """
    doc = await _users().find_one(
        {"user_id": user_id},
        {"first_name": 1, "username": 1}
    )
    if doc:
        return doc.get("first_name") or f"User {user_id}", doc.get("username")
    return f"User {user_id}", None


async def get_mention_data_batch(user_ids: list[int]) -> dict[int, tuple[str, str | None]]:
    """Fetch (first_name, username) for multiple users in a single query.

    Optimized batch query that replaces multiple individual get_user_mention_data()
    calls with a single database roundtrip.
    """
    if not user_ids:
        return {}
    docs = await _users().find(
        {"user_id": {"$in": user_ids}},
        {"user_id": 1, "first_name": 1, "username": 1}
    ).to_list(None)
    result = {
        doc["user_id"]: (
            doc.get("first_name") or f"User {doc['user_id']}",
            doc.get("username")
        ) for doc in docs
    }
    # Fill in missing users with defaults
    for uid in user_ids:
        if uid not in result:
            result[uid] = (f"User {uid}", None)
    return result


async def get_first_names_batch(user_ids: list[int]) -> dict[int, str]:
    """Fetch first names for multiple users in a single query.

    Optimized batch query that replaces multiple individual get_first_name()
    calls with a single database roundtrip.
    """
    if not user_ids:
        return {}
    docs = await _users().find(
        {"user_id": {"$in": user_ids}},
        {"user_id": 1, "first_name": 1}
    ).to_list(None)
    result = {
        doc["user_id"]: doc.get("first_name") or f"User {doc['user_id']}"
        for doc in docs
    }
    # Fill in missing users with defaults
    for uid in user_ids:
        if uid not in result:
            result[uid] = f"User {uid}"
    return result


async def get_first_name(user_id: int, fallback: str = "") -> str:
    """Return cached first_name or fallback string."""
    doc = await _users().find_one({"user_id": user_id}, {"first_name": 1})
    if doc:
        return doc.get("first_name") or fallback
    return fallback


async def total_users() -> int:
    """Get the total number of unique users in the cache."""
    return await _users().count_documents({})


async def all_users(*, sort_by: str = "first_name") -> list[UserDoc]:
    """Return every cached user, sorted by ``sort_by`` (default: first name).

    Used by the ``/tcstats`` Users drill-down. Sorted server-side so the
    paginated view does not need to sort in-process for large caches.
    """
    sort_dir = 1 if sort_by != "last_updated" else -1
    return (
        await _users().find({}, {"_id": 0}).sort(sort_by, sort_dir).to_list(length=None)
    )


# ─────────────────────────── Owner CRUD ─────────────────────────── #


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


async def ensure_initial_owner(initial_id: int) -> None:
    """Create the first owner entry if the owners collection is empty."""
    if await _owners().count_documents({}) > 0:
        return
    try:
        await _owners().insert_one({"user_id": initial_id})
        owner_id_cache.put(_OWNER_KEY, initial_id)
    except DuplicateKeyError:
        # * Another instance won the startup race; drop the cache so the next read refreshes.
        owner_id_cache.invalidate(_OWNER_KEY)


async def set_owner(user_id: int) -> None:
    """Replace the current owner with user_id; clears the role cache."""
    # * Insert the new owner first so a mid-flight crash leaves the new owner present,
    # * not zero owners. The unique index on user_id makes the upsert idempotent.
    await _owners().update_one(
        {"user_id": user_id},
        {"$setOnInsert": {"user_id": user_id}},
        upsert=True,
    )
    await _owners().delete_many({"user_id": {"$ne": user_id}})
    owner_id_cache.put(_OWNER_KEY, user_id)
    # * Clear the full role cache – the old owner's ID is unknown
    effective_role_cache.clear()


# ─────────────────────────── Admin CRUD ─────────────────────────── #


async def is_admin(user_id: int) -> bool:
    """Return True if user_id is a registered admin."""
    return await _admins().find_one({"user_id": user_id}, {"_id": 1}) is not None


async def is_staff(user_id: int) -> bool:
    """Return True if user_id is owner or admin."""
    owner, admin = await asyncio.gather(is_owner(user_id), is_admin(user_id))
    return owner or admin


async def add_admin(user_id: int, promoted_by: int) -> None:
    """Add a new admin via upsert; no-op if already present."""
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


async def all_admins() -> list[AdminDoc]:
    """Return all admin documents."""
    return await _admins().find({}, {"_id": 0, "user_id": 1}).to_list(None)


async def admin_count() -> int:
    """Return the total count of registered admins."""
    return await _admins().count_documents({})


# ────────────────── Custom role CRUD (dev / tester) ─────────────── #


async def set_role(user_id: int, role: str, assigned_by: int) -> None:
    """Assign a custom role (developer/tester) to a user."""
    await _roles().update_one(
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
    r = await _roles().delete_one({"user_id": user_id})
    effective_role_cache.invalidate(user_id)
    return r.deleted_count > 0


async def get_role(user_id: int) -> str | None:
    """Get a user's custom role from the database only."""
    doc = await _roles().find_one({"user_id": user_id}, {"role": 1})
    return doc["role"] if doc else None


async def all_by_role(role: str) -> list[RoleRefDoc]:
    """Get all users with a specific custom role."""
    return await _roles().find({"role": role}, {"_id": 0, "user_id": 1}).to_list(None)


async def all_roles() -> list[RoleDoc]:
    """Get all custom role assignments in the database."""
    return await _roles().find({}).to_list(None)


# ───────────────────── Effective role resolution ────────────────── #


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


async def role_meta(user_id: int) -> tuple[str | None, int | None, object]:
    """Return ``(role, assigned_by, assigned_at)`` — owner has no metadata."""
    role = await get_effective_role(user_id)
    if role is None:
        return None, None, None
    if role == "founder":
        # * tc_owners stores only user_id; no metadata to surface.
        return role, None, None
    if role == "admin":
        doc = await _admins().find_one(
            {"user_id": user_id},
            {"_id": 0, "promoted_by": 1, "promoted_date": 1},
        )
        if doc:
            return role, doc.get("promoted_by"), doc.get("promoted_date")
        return role, None, None
    doc = await _roles().find_one(
        {"user_id": user_id},
        {"_id": 0, "assigned_by": 1, "assigned_at": 1},
    )
    if doc:
        return role, doc.get("assigned_by"), doc.get("assigned_at")
    return role, None, None
