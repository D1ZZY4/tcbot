# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Studio

"""Member profile cache helpers.

This module handles all member_cache collection operations for Telegram user profiles.
Do not mix with users_roles.py which handles tc_owners, tc_admins, and tc_roles.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, cast

from tcbot.database.cache import CACHE_MISS, user_mention_cache
from tcbot.database.documents import UserDoc
from tcbot.database.mongos import col, db_call
from tcbot.utils.timedate_format import utc_now

if TYPE_CHECKING:
    from motor.motor_asyncio import AsyncIOMotorCollection

# ─────────────────────── Collection Helpers ─────────────────────── #
# * Internal collection access utilities for the member_cache database


def _members() -> AsyncIOMotorCollection:
    return col("member_cache")


# ────────── Member cache mutations ─────────


async def upsert_user(
    user_id: int,
    username: str | None,
    first_name: str,
    last_name: str | None = None,
) -> None:
    """Update or insert a user's profile information into the cache."""
    now = utc_now()
    await db_call(
        _members().update_one(
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
    )
    # * Invalidate mention cache so the next read reflects the updated profile.
    user_mention_cache.invalidate(user_id)


async def upsert_user_if_changed(
    user_id: int,
    username: str | None,
    first_name: str,
    last_name: str | None = None,
) -> bool:
    """Write user profile to DB only when identity data has changed since last cache entry.

    Checks the L1 in-memory mention cache first.  When the cached (first_name,
    username) pair matches the incoming data, the DB write is skipped entirely
    and False is returned.  This eliminates the MongoDB round-trip for the vast
    majority of updates (where identity data has not changed) and makes the
    hot-path member-cache handler nearly free.

    Returns True when a DB write was performed, False when skipped.
    """
    cached = user_mention_cache.get(user_id)
    if cached is not CACHE_MISS:
        # * Cache stores [first_name, username]; compare the two cheap string fields.
        data: list[str | None] = cached  # type: ignore[assignment]
        if data[0] == first_name and data[1] == username:
            return False
    await upsert_user(user_id, username, first_name, last_name)
    return True


# ───────── Member cache queries ─────────


async def get_user(user_id: int) -> UserDoc | None:
    """Get the full cached profile for a specific user."""
    return await db_call(_members().find_one({"user_id": user_id}))


async def get_user_mention_data(user_id: int) -> tuple[str, str | None]:
    """Return (first_name, username) for mention formatting (L1->L2->DB cached).

    Uses ``user_mention_cache`` (Redis-backed TwoLevelCache) to avoid MongoDB
    round-trips on repeated lookups.  Cache is invalidated on every ``upsert_user``.
    """

    async def _fetch() -> list[str | None]:
        doc = await db_call(
            _members().find_one({"user_id": user_id}, {"first_name": 1, "username": 1})
        )
        if doc:
            return [doc.get("first_name") or str(user_id), doc.get("username")]
        return [str(user_id), None]

    data = await user_mention_cache.get_or_fetch(user_id, _fetch)
    return cast("tuple[str, str | None]", (data[0], data[1]))


async def get_mention_data_batch(
    user_ids: list[int],
) -> dict[int, tuple[str, str | None]]:
    """Fetch (first_name, username) for multiple users, checking cache for each ID first.

    Cache-aware: IDs found in L1 are returned immediately; only uncached IDs trigger
    a batch MongoDB query.  Newly fetched data is populated into the mention cache.
    """
    if not user_ids:
        return {}

    result: dict[int, tuple[str, str | None]] = {}
    missing: list[int] = []

    # * Check L1 in-memory cache for each user_id before hitting MongoDB.
    for uid in user_ids:
        cached = user_mention_cache.get(uid)
        if cached is not CACHE_MISS:
            data = cast("list[str | None]", cached)
            result[uid] = (cast("str", data[0]), cast("str | None", data[1]))
        else:
            missing.append(uid)

    if not missing:
        return result

    # * Batch-fetch only uncached users from MongoDB in a single round-trip.
    docs = await db_call(
        _members()
        .find(
            {"user_id": {"$in": missing}},
            {"user_id": 1, "first_name": 1, "username": 1},
        )
        .to_list(None)
    )
    for doc in docs:
        uid = doc["user_id"]
        fname = doc.get("first_name") or str(uid)
        uname = doc.get("username")
        # * Populate L1 (and fire-and-forget L2 Redis write) for next lookup.
        user_mention_cache.put(uid, [fname, uname])
        result[uid] = (fname, uname)

    # * Fill fallback for users not found in DB either.
    for uid in missing:
        if uid not in result:
            result[uid] = (str(uid), None)

    return result


async def get_first_names_batch(user_ids: list[int]) -> dict[int, str]:
    """Fetch first names for multiple users in a single query.

    Optimized batch query that replaces multiple individual get_first_name()
    calls with a single database roundtrip.
    """
    if not user_ids:
        return {}
    docs = await db_call(
        _members()
        .find({"user_id": {"$in": user_ids}}, {"user_id": 1, "first_name": 1})
        .to_list(None)
    )
    result = {
        doc["user_id"]: doc.get("first_name") or str(doc["user_id"]) for doc in docs
    }
    # Fill in missing users with defaults
    for uid in user_ids:
        if uid not in result:
            result[uid] = str(uid)
    return result


async def get_first_name(user_id: int, fallback: str = "") -> str:
    """Return cached first_name or fallback string.

    Checks L1 mention cache before hitting MongoDB so repeated lookups in
    the same process avoid a network round-trip.
    """
    cached = user_mention_cache.get(user_id)
    if cached is not CACHE_MISS:
        data = cast("list[str | None]", cached)
        return cast("str", data[0]) or fallback

    doc = await db_call(_members().find_one({"user_id": user_id}, {"first_name": 1}))
    if doc:
        return doc.get("first_name") or fallback
    return fallback


async def total_users() -> int:
    """Get the total number of unique users in the cache."""
    return await db_call(_members().estimated_document_count())


async def all_users(*, sort_by: str = "first_name") -> list[UserDoc]:
    """Return every cached user, sorted by ``sort_by`` (default: first name).

    Used by the ``/tcstats`` Users drill-down. Sorted server-side so the
    paginated view does not need to sort in-process for large caches.
    """
    sort_dir = 1 if sort_by != "last_updated" else -1
    return await db_call(
        _members().find({}, {"_id": 0}).sort(sort_by, sort_dir).to_list(length=None)
    )


async def search_by_name(needle: str, limit: int = 5) -> list[UserDoc]:
    """Return up to ``limit`` cached users whose name or username contains ``needle``.

    Runs a server-side case-insensitive regex query with a result cap so only
    matching documents (and only the fields needed for target resolution) travel
    over the wire, regardless of cache size. This replaces the old pattern of
    loading all users into Python and scanning linearly.
    """
    if not needle:
        return []
    pattern = {"$regex": re.escape(needle), "$options": "i"}
    return await db_call(
        _members()
        .find(
            {"$or": [{"first_name": pattern}, {"username": pattern}]},
            {"user_id": 1, "first_name": 1, "username": 1, "_id": 0},
        )
        .limit(limit)
        .to_list(length=limit)
    )
