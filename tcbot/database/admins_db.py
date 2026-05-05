# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
## Owners and admins collection helpers
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from tcbot.database.mongos import col


def _owners():
    return col("tc_owners")


def _admins():
    return col("tc_admins")


async def get_owner_id() -> int | None:
    doc = await _owners().find_one({})
    return doc["user_id"] if doc else None


async def is_owner(user_id: int) -> bool:
    return await _owners().find_one({"user_id": user_id}) is not None


async def is_admin(user_id: int) -> bool:
    return await _admins().find_one({"user_id": user_id}) is not None


async def is_staff(user_id: int) -> bool:
    """True if owner or admin — both checks run in parallel."""
    owner, admin = await asyncio.gather(is_owner(user_id), is_admin(user_id))
    return owner or admin


async def ensure_initial_owner(initial_id: int) -> None:
    if await _owners().count_documents({}) == 0:
        await _owners().insert_one({"user_id": initial_id})


async def set_owner(user_id: int) -> None:
    await _owners().delete_many({})
    await _owners().insert_one({"user_id": user_id})


async def add_admin(user_id: int, promoted_by: int) -> None:
    await _admins().update_one(
        {"user_id": user_id},
        {"$setOnInsert": {
            "user_id": user_id,
            "promoted_by": promoted_by,
            "promoted_date": datetime.now(timezone.utc),
        }},
        upsert=True,
    )


async def remove_admin(user_id: int) -> bool:
    r = await _admins().delete_one({"user_id": user_id})
    return r.deleted_count > 0


async def all_admins() -> list[dict]:
    return await _admins().find({}).to_list(None)


async def admin_count() -> int:
    return await _admins().count_documents({})
