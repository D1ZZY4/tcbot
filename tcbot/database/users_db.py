# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""Member cache collection – stores first_name, last_name, username per spec."""
from __future__ import annotations

from datetime import datetime, timezone

from tcbot.database.mongos import col


def _users():
    return col("member_cache")


async def upsert_user(
    user_id: int,
    username: str | None,
    first_name: str,
    last_name: str | None = None,
) -> None:
    await _users().update_one(
        {"user_id": user_id},
        {"$set": {
            "user_id": user_id,
            "username": username,
            "first_name": first_name,
            "last_name": last_name,
            "last_updated": datetime.now(timezone.utc),
        }},
        upsert=True,
    )


async def get_user(user_id: int) -> dict | None:
    return await _users().find_one({"user_id": user_id})


async def get_first_name(user_id: int, fallback: str = "") -> str:
    """Return cached first_name or fallback string."""
    doc = await _users().find_one({"user_id": user_id}, {"first_name": 1})
    if doc:
        return doc.get("first_name") or fallback
    return fallback


async def total_users() -> int:
    return await _users().count_documents({})
