# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Member profile cache: reads, batch lookups, search, and paging."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, cast

from tcbot.database.cache import CACHE_MISS, user_mention_cache
from tcbot.database.documents import UserDoc
from tcbot.database.mongos import col, db_call

if TYPE_CHECKING:
    from motor.motor_asyncio import AsyncIOMotorCollection


def _members() -> AsyncIOMotorCollection:
    return col("member_cache")


# * L1 mention-cache entries are [first_name, username, last_name] triples.
# * Readers only use indexes 0 and 1; index 2 exists so change detection
# * notices last_name-only updates. The not-found sentinel is all-None.
_NOT_FOUND_SENTINEL: list[str | None] = [None, None, None]


def _cached_triple(data: list[str | None]) -> tuple[str | None, str | None, str | None]:
    """Split a cache entry into (first_name, username, last_name).

    Legacy L2 pairs stored before last_name tracking have length 2; the
    missing element reads as None, which correctly counts as changed.
    """
    return (
        data[0] if len(data) > 0 else None,
        data[1] if len(data) > 1 else None,
        data[2] if len(data) > 2 else None,
    )


async def _fetch_mention_triple(user_id: int) -> list[str | None]:
    """Read (first_name, username, last_name) for the mention cache.

    Single owner for the projection and the not-found sentinel so the
    cached mention readers cannot drift apart.
    """
    doc = await db_call(
        _members().find_one(
            {"user_id": user_id}, {"first_name": 1, "username": 1, "last_name": 1}
        )
    )
    if doc:
        return [
            doc.get("first_name") or str(user_id),
            doc.get("username"),
            doc.get("last_name"),
        ]
    # * Sentinel: user has no member_cache document. All-None is used
    # * (not [str(user_id), None, None]) so the not-found case is unambiguous:
    # * a real first_name is never None, but str(user_id) could coincide
    # * with an actual numeric display name and would suppress fallback.
    return list(_NOT_FOUND_SENTINEL)


async def get_user(user_id: int) -> UserDoc | None:
    """Get the full cached profile for a specific user."""
    return await db_call(_members().find_one({"user_id": user_id}))


async def get_user_mention_data(user_id: int) -> tuple[str, str | None]:
    """Return (first_name, username) for mention formatting (L1->L2->DB cached).

    Uses ``user_mention_cache`` (Redis-backed TwoLevelCache) to avoid MongoDB
    round-trips on repeated lookups.  Cache is invalidated on every ``upsert_user``.

    Cache sentinel: ``[None, None, None]`` is stored when the user has no document in
    ``member_cache``.  The consumer converts ``None`` → ``str(user_id)`` so the
    returned tuple always contains a non-empty string as the first element.
    """

    async def _fetch() -> list[str | None]:
        return await _fetch_mention_triple(user_id)

    data = await user_mention_cache.get_or_fetch(user_id, _fetch)
    # * data[0] is None when the user has no member_cache document (sentinel).
    name = cast("str", data[0]) if data[0] is not None else str(user_id)
    return (name, data[1])


async def _mention_triples(
    user_ids: list[int],
) -> dict[int, list[str | None]]:
    """Return {uid: [first_name|None-sentinel, username, last_name]} for every ID.

    Single owner for the batch-miss path shared by :func:`get_mention_data_batch`
    and :func:`get_first_names_batch`: L1 hits served without I/O (repeat IDs
    dropped via ``dict.fromkeys``), the remainder fetched in one ``$in``
    query, full triples populated into L1, and absent users sentineled so
    repeat renders skip the round-trip. Miss semantics cannot drift between
    readers when only one function implements them.
    """
    result: dict[int, list[str | None]] = {}
    missing: list[int] = []
    for uid in dict.fromkeys(user_ids):
        cached = user_mention_cache.get(uid)
        if cached is not CACHE_MISS:
            result[uid] = cast("list[str | None]", cached)
        else:
            missing.append(uid)
    if not missing:
        return result
    # * Batch-fetch only uncached users from MongoDB in a single round-trip.
    docs = await db_call(
        _members()
        .find(
            {"user_id": {"$in": missing}},
            {"user_id": 1, "first_name": 1, "username": 1, "last_name": 1},
        )
        .to_list(None)
    )
    for doc in docs:
        uid = doc["user_id"]
        # * Populate L1 (and fire-and-forget L2 Redis write) for next lookup.
        triple = [
            doc.get("first_name") or str(uid),
            doc.get("username"),
            doc.get("last_name"),
        ]
        user_mention_cache.put(uid, triple)
        result[uid] = triple
    # * Fill fallback for users not found in DB either and cache the sentinel so
    # * subsequent calls skip the MongoDB round-trip on the next lookup.
    for uid in missing:
        if uid not in result:
            user_mention_cache.put(uid, list(_NOT_FOUND_SENTINEL))
            result[uid] = list(_NOT_FOUND_SENTINEL)
    return result


async def get_mention_data_batch(
    user_ids: list[int],
) -> dict[int, tuple[str, str | None]]:
    """Fetch (first_name, username) for multiple users, checking cache for each ID first.

    Cache-aware: IDs found in L1 are returned immediately; only uncached IDs trigger
    a batch MongoDB query.  Newly fetched data is populated into the mention cache.
    """
    triples = await _mention_triples(user_ids)
    result: dict[int, tuple[str, str | None]] = {}
    for uid, data in triples.items():
        # * data[0] may be None (not-found sentinel); fall back to str(uid).
        fname = cast("str", data[0]) if data[0] is not None else str(uid)
        result[uid] = (
            fname,
            cast("str | None", data[1] if len(data) > 1 else None),
        )
    return result


async def get_first_names_batch(user_ids: list[int]) -> dict[int, str]:
    """Fetch first names for multiple users, checking L1 first.

    IDs already in the in-memory mention cache are served without I/O; only
    uncached IDs trigger one batch MongoDB query. Users missing from the DB
    get the not-found sentinel cached so repeat renders skip the round-trip.
    Found rows populate the full mention triple (the projection covers
    first_name, username, and last_name, exactly like
    :func:`_fetch_mention_triple`), so repeat renders by any reader skip
    the round-trip without corrupting change detection.
    """
    triples = await _mention_triples(user_ids)
    return {
        uid: (cast("str", data[0]) if data[0] is not None else str(uid))
        for uid, data in triples.items()
    }


async def get_first_name(user_id: int, fallback: str = "") -> str:
    """Return cached first_name or caller's fallback (L1 → L2 Redis → DB cached).

    Routes through ``user_mention_cache.get_or_fetch`` so all three layers are
    checked in order and both L1 and L2 are populated on a miss -- exactly the
    same path as ``get_user_mention_data``.  Calling this function never causes
    a redundant MongoDB round-trip for a user already fetched by either helper.

    When the user has no document in ``member_cache``, ``_fetch`` stores the
    sentinel ``[None, None, None]`` in the cache.  The sentinel is distinguished from a
    real name so the caller's ``fallback`` is returned instead of a raw numeric ID
    string (e.g. ``"Admin"`` instead of ``"123456789"``).
    """

    async def _fetch() -> list[str | None]:
        return await _fetch_mention_triple(user_id)

    data = await user_mention_cache.get_or_fetch(user_id, _fetch)
    # * data[0] is None when the sentinel is in cache (user not in member_cache DB).
    # * Use caller's fallback in that case; otherwise return the real name.
    return cast("str", data[0]) if data[0] is not None else fallback


async def total_users() -> int:
    """Get the total number of unique users in the cache."""
    return await db_call(_members().estimated_document_count())


# * Allowed sort keys for all_users_page(). Unvalidated strings would force an
# * unindexed COLLSCAN plus an in-memory sort. Only indexed fields qualify:
# * member_cache has indexes on user_id, username, first_name, and
# * last_updated (TTL); last_name and commit_date sorts are refused.
_ALLOWED_USER_SORTS: frozenset[str] = frozenset(
    {"user_id", "username", "first_name", "last_updated"}
)


async def all_users_page(
    *, skip: int = 0, limit: int = 200, sort_by: str = "first_name"
) -> list[UserDoc]:
    """Return one page of cached users (server-side skip/limit).

    Prefer this over :func:`all_users` for paginated views: only the
    visible slice travels over the wire regardless of cache size.
    """
    if sort_by not in _ALLOWED_USER_SORTS:
        sort_by = "first_name"
    sort_dir = 1 if sort_by != "last_updated" else -1
    # * Clamp once so cursor limit and fetch length can never disagree;
    # * callers always pass positive values, this only pins the edge.
    page_size = max(1, limit)
    return await db_call(
        _members()
        .find(
            {},
            {
                "_id": 0,
                "user_id": 1,
                "username": 1,
                "first_name": 1,
                "last_name": 1,
                "commit_date": 1,
                "last_updated": 1,
            },
        )
        .sort(sort_by, sort_dir)
        .skip(max(0, skip))
        .limit(page_size)
        .to_list(length=page_size)
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
    # * Anchored so "dan" matches a name that starts with "dan" (e.g. "daniel"),
    # * not one that merely contains "dan" mid-string (e.g. "randy").
    pattern = {"$regex": f"^{re.escape(needle)}", "$options": "i"}
    return await db_call(
        _members()
        .find(
            {"$or": [{"first_name": pattern}, {"username": pattern}]},
            {"user_id": 1, "first_name": 1, "username": 1, "_id": 0},
        )
        .limit(limit)
        .to_list(length=limit)
    )
