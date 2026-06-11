# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Studio

"""Federated groups and pending joins collection helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from tcbot.database.cache import (
    _ALL_GROUPS_KEY,
    CACHE_MISS,
    active_groups_cache,
    connected_cache,
)
from tcbot.database.documents import GroupDoc, PendingGroupDoc
from tcbot.database.mongos import col
from tcbot.utils.timedate_format import utc_now

if TYPE_CHECKING:
    from motor.motor_asyncio import AsyncIOMotorCollection

# ─────────────────────── Collection Helpers ─────────────────────── #
# * Internal collection access utilities for groups database


def _groups() -> AsyncIOMotorCollection:
    return col("federated_groups")


def _pending() -> AsyncIOMotorCollection:
    return col("pending_joins")


# ──────────────────── Group Queries & Mutations ─────────────────── #
# * Functions to manage active connected groups in the federation
# * Includes caching to minimize database roundtrips
# ! CRITICAL: Cache invalidation is crucial here - always clear caches on changes


async def get_group(chat_id: int) -> GroupDoc | None:
    """Get the full group record for a specific chat ID."""
    return await _groups().find_one({"chat_id": chat_id})


async def get_group_titles(chat_ids: list[int]) -> dict[int, str]:
    """Return {chat_id: title} for the given chat_ids; missing groups are absent."""
    if not chat_ids:
        return {}
    docs = (
        await _groups()
        .find({"chat_id": {"$in": chat_ids}}, {"_id": 0, "chat_id": 1, "title": 1})
        .to_list(length=None)
    )
    return {int(d["chat_id"]): d.get("title") or str(d["chat_id"]) for d in docs}


async def is_connected(chat_id: int) -> bool:
    """Check if a group is currently active and connected to the federation."""
    cached = connected_cache.get(chat_id)
    if cached is not CACHE_MISS:
        return cast("bool", cached)
    result = (
        await _groups().find_one({"chat_id": chat_id, "is_active": True}, {"_id": 1})
        is not None
    )
    connected_cache.put(chat_id, result)
    return result


async def add_group(chat_id: int, title: str, added_by: int) -> None:
    """Add or update a group in the federated_groups collection."""
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
    """Mark a group as inactive (disconnect from federation)."""
    r = await _groups().update_one({"chat_id": chat_id}, {"$set": {"is_active": False}})
    connected_cache.put(chat_id, False)
    active_groups_cache.clear()
    return r.matched_count > 0


async def active_groups() -> list[GroupDoc]:
    """Get all currently active and connected groups."""
    cached = active_groups_cache.get(_ALL_GROUPS_KEY)
    if cached is not CACHE_MISS:
        return cast("list[GroupDoc]", cached)
    result: list[GroupDoc] = await _groups().find({"is_active": True}).to_list(None)
    active_groups_cache.put(_ALL_GROUPS_KEY, result)
    return result


async def active_group_count() -> int:
    """Count the number of currently active connected groups."""
    return await _groups().count_documents({"is_active": True})


# ──────────────────── Pending Joins Management ──────────────────── #
# * Functions to manage groups waiting to be approved into the federation
# * Tracks join requests with all necessary metadata


async def add_pending(chat_id: int, title: str, owner_id: int, message_id: int) -> None:
    """Add or update a pending join request from a group."""
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
    """Get a pending join request by chat ID."""
    return await _pending().find_one({"chat_id": chat_id})


async def remove_pending(chat_id: int) -> None:
    """Remove a pending join request after it's approved or rejected."""
    await _pending().delete_one({"chat_id": chat_id})
