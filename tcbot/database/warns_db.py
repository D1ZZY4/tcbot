# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""Warnings collection helpers - manages user warning records in groups."""

from __future__ import annotations

from pymongo import ReturnDocument

from tcbot.database.documents import WarnCountDoc, WarnDoc
from tcbot.database.mongos import col
from tcbot.utils.timedate_format import utc_now

# ─────────────────────── Collection Helpers ─────────────────────── #
# * Internal collection access utilities for the warns database


def _warns():
    return col("warns")


def _warn_counts():
    return col("warn_counts")


def _warn_key(user_id: int, chat_id: int) -> dict[str, int]:
    return {"user_id": user_id, "chat_id": chat_id}


async def _sync_warn_count(user_id: int, chat_id: int) -> int:
    """Read the counter doc, or backfill it from warn history when missing."""
    doc: WarnCountDoc | None = await _warn_counts().find_one(
        _warn_key(user_id, chat_id),
        {"_id": 0, "count": 1},
    )
    if doc is not None:
        return int(doc.get("count", 0))

    count = await _warns().count_documents(_warn_key(user_id, chat_id))
    if count > 0:
        await _warn_counts().update_one(
            _warn_key(user_id, chat_id),
            {
                "$set": {
                    "count": count,
                    "updated_at": utc_now(),
                },
                "$setOnInsert": {
                    "user_id": user_id,
                    "chat_id": chat_id,
                },
            },
            upsert=True,
        )
    return count


async def _store_warn_count(user_id: int, chat_id: int, count: int) -> None:
    """Persist the counter doc for a user/chat pair."""
    if count <= 0:
        await _warn_counts().delete_one(_warn_key(user_id, chat_id))
        return
    await _warn_counts().update_one(
        _warn_key(user_id, chat_id),
        {
            "$set": {
                "count": count,
                "updated_at": utc_now(),
            },
            "$setOnInsert": {
                "user_id": user_id,
                "chat_id": chat_id,
            },
        },
        upsert=True,
    )


# ──────────────────────────── Mutations ─────────────────────────── #
# * Functions that modify warning records in the database
# * Includes adding, removing, and clearing warnings
# ! CRITICAL: These functions modify per-chat warning counts


async def add_warn(user_id: int, reason: str, admin_id: int, chat_id: int) -> int:
    """Add a new warning to a user in a specific chat."""
    c = _warns()
    inserted = await c.insert_one(
        {
            "user_id": user_id,
            "reason": reason,
            "admin_id": admin_id,
            "chat_id": chat_id,
            "timestamp": utc_now(),
        }
    )
    try:
        counter = await _warn_counts().find_one_and_update(
            _warn_key(user_id, chat_id),
            {
                "$inc": {"count": 1},
                "$set": {"updated_at": utc_now()},
                "$setOnInsert": {
                    "user_id": user_id,
                    "chat_id": chat_id,
                    "count": 0,
                },
            },
            upsert=True,
            return_document=ReturnDocument.AFTER,
            projection={"_id": 0, "count": 1},
        )
    except Exception:
        await c.delete_one({"_id": inserted.inserted_id})
        raise
    if counter is None:
        return await _sync_warn_count(user_id, chat_id)
    return int(counter.get("count", 0))


# ─────────────────────── Queries & Retrieval ────────────────────── #
# * Functions to fetch warning data from the database
# * Includes counting, listing, and retrieving user warnings


async def warn_count(user_id: int, chat_id: int) -> int:
    """Get the current number of warnings for a user in a specific chat."""
    return await _sync_warn_count(user_id, chat_id)


async def clear_warns(user_id: int, chat_id: int) -> int:
    """Remove ALL warnings for a user in a specific chat."""
    r = await _warns().delete_many(_warn_key(user_id, chat_id))
    await _warn_counts().delete_one(_warn_key(user_id, chat_id))
    return r.deleted_count


async def get_warns(user_id: int, chat_id: int) -> list[WarnDoc]:
    """Return all warn documents for a user in a chat, oldest first."""
    cursor = _warns().find(
        {"user_id": user_id, "chat_id": chat_id},
        sort=[("timestamp", 1)],
    )
    return await cursor.to_list(length=None)


async def remove_last_warn(user_id: int, chat_id: int) -> bool:
    """Delete the most recent warn document. Returns True if one was removed."""
    doc = await _warns().find_one(
        _warn_key(user_id, chat_id),
        sort=[("timestamp", -1), ("_id", -1)],
    )
    if not doc:
        return False
    await _warns().delete_one({"_id": doc["_id"]})
    counter = await _warn_counts().find_one_and_update(
        {
            **_warn_key(user_id, chat_id),
            "count": {"$gt": 0},
        },
        {"$inc": {"count": -1}, "$set": {"updated_at": utc_now()}},
        return_document=ReturnDocument.AFTER,
        projection={"_id": 0, "count": 1},
    )
    if counter is None:
        await _store_warn_count(
            user_id,
            chat_id,
            await _warns().count_documents(_warn_key(user_id, chat_id)),
        )
    return True
