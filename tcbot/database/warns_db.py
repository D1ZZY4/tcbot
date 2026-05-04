# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""Warnings collection helpers."""
from __future__ import annotations

from datetime import datetime, timezone

from tcbot.database.mongos import col


def _warns():
    return col("warns")


async def add_warn(user_id: int, reason: str, admin_id: int, chat_id: int) -> int:
    c = _warns()
    await c.insert_one({
        "user_id": user_id,
        "reason": reason,
        "admin_id": admin_id,
        "chat_id": chat_id,
        "timestamp": datetime.now(timezone.utc),
    })
    return await c.count_documents({"user_id": user_id, "chat_id": chat_id})


async def warn_count(user_id: int, chat_id: int) -> int:
    return await _warns().count_documents({"user_id": user_id, "chat_id": chat_id})


async def clear_warns(user_id: int, chat_id: int) -> int:
    r = await _warns().delete_many({"user_id": user_id, "chat_id": chat_id})
    return r.deleted_count


async def get_warns(user_id: int, chat_id: int) -> list[dict]:
    """Return all warn documents for a user in a chat, oldest first."""
    cursor = _warns().find(
        {"user_id": user_id, "chat_id": chat_id},
        sort=[("timestamp", 1)],
    )
    return await cursor.to_list(length=None)


async def remove_last_warn(user_id: int, chat_id: int) -> bool:
    """Delete the most recent warn document. Returns True if one was removed."""
    doc = await _warns().find_one(
        {"user_id": user_id, "chat_id": chat_id},
        sort=[("timestamp", -1)],
    )
    if not doc:
        return False
    await _warns().delete_one({"_id": doc["_id"]})
    return True
