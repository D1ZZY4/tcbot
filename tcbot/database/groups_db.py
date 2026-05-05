# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
## Federated groups and pending joins collection helpers
from __future__ import annotations

from datetime import datetime, timezone

from tcbot.database.mongos import col


def _groups():
    return col("federated_groups")


def _pending():
    return col("pending_joins")


async def get_group(chat_id: int) -> dict | None:
    return await _groups().find_one({"chat_id": chat_id})


async def is_affiliated(chat_id: int) -> bool:
    return await _groups().find_one({"chat_id": chat_id, "is_active": True}) is not None


async def add_group(chat_id: int, title: str, added_by: int) -> None:
    await _groups().update_one(
        {"chat_id": chat_id},
        {"$set": {
            "chat_id": chat_id,
            "title": title,
            "added_by": added_by,
            "added_date": datetime.now(timezone.utc),
            "is_active": True,
        }},
        upsert=True,
    )


async def deactivate_group(chat_id: int) -> bool:
    r = await _groups().update_one({"chat_id": chat_id}, {"$set": {"is_active": False}})
    return r.matched_count > 0


async def active_groups() -> list[dict]:
    return await _groups().find({"is_active": True}).to_list(None)


async def active_group_count() -> int:
    return await _groups().count_documents({"is_active": True})


## Pending joins

async def add_pending(chat_id: int, title: str, owner_id: int, message_id: int) -> None:
    await _pending().update_one(
        {"chat_id": chat_id},
        {"$set": {
            "chat_id": chat_id,
            "title": title,
            "owner_id": owner_id,
            "message_id": message_id,
            "added_date": datetime.now(timezone.utc),
        }},
        upsert=True,
    )


async def get_pending(chat_id: int) -> dict | None:
    return await _pending().find_one({"chat_id": chat_id})


async def remove_pending(chat_id: int) -> None:
    await _pending().delete_one({"chat_id": chat_id})
