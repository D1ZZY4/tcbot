# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
## Federated groups and pending joins collection helpers
from __future__ import annotations

from datetime import datetime, timezone

from tcbot.database.cache import (
    CACHE_MISS,
    _ALL_GROUPS_KEY,
    active_groups_cache,
    affiliated_cache,
)
from tcbot.database.mongos import col


def _groups():
    return col("federated_groups")


def _pending():
    return col("pending_joins")


async def get_group(chat_id: int) -> dict | None:
    return await _groups().find_one({"chat_id": chat_id})


async def is_affiliated(chat_id: int) -> bool:
    cached = affiliated_cache.get(chat_id)
    if cached is not CACHE_MISS:
        return cached  # type: ignore[return-value]
    result = (
        await _groups().find_one({"chat_id": chat_id, "is_active": True}, {"_id": 1})
        is not None
    )
    affiliated_cache.put(chat_id, result)
    return result


async def add_group(chat_id: int, title: str, added_by: int) -> None:
    await _groups().update_one(
        {"chat_id": chat_id},
        {"$set": {
            "chat_id":    chat_id,
            "title":      title,
            "added_by":   added_by,
            "added_date": datetime.now(timezone.utc),
            "is_active":  True,
        }},
        upsert=True,
    )
    affiliated_cache.put(chat_id, True)
    active_groups_cache.clear()


async def deactivate_group(chat_id: int) -> bool:
    r = await _groups().update_one({"chat_id": chat_id}, {"$set": {"is_active": False}})
    affiliated_cache.put(chat_id, False)
    active_groups_cache.clear()
    return r.matched_count > 0


async def active_groups() -> list[dict]:
    cached = active_groups_cache.get(_ALL_GROUPS_KEY)
    if cached is not CACHE_MISS:
        return cached  # type: ignore[return-value]
    result: list[dict] = await _groups().find({"is_active": True}).to_list(None)
    active_groups_cache.put(_ALL_GROUPS_KEY, result)
    return result


async def active_group_count() -> int:
    return await _groups().count_documents({"is_active": True})


## Pending joins

async def add_pending(chat_id: int, title: str, owner_id: int, message_id: int) -> None:
    await _pending().update_one(
        {"chat_id": chat_id},
        {"$set": {
            "chat_id":    chat_id,
            "title":      title,
            "owner_id":   owner_id,
            "message_id": message_id,
            "added_date": datetime.now(timezone.utc),
        }},
        upsert=True,
    )


async def get_pending(chat_id: int) -> dict | None:
    return await _pending().find_one({"chat_id": chat_id})


async def remove_pending(chat_id: int) -> None:
    await _pending().delete_one({"chat_id": chat_id})
