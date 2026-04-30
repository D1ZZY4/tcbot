# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""Repository helpers for the per-(chat, user) ``member_cache`` collection."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from .mongo import member_cache


async def upsert(
    *,
    chat_id: int,
    user_id: int,
    when: datetime,
    first_name: str | None = None,
    username: str | None = None,
    status: str | None = None,
) -> None:
    """Update ``last_seen`` and any provided identity / status fields.

    Only fields with a non-``None`` argument are written, so a status-only
    update from ``chat_member`` events does not clobber a known username.
    """
    payload: dict[str, Any] = {"last_seen": when}
    if first_name is not None:
        payload["first_name"] = first_name
    if username is not None:
        payload["username"] = username
    if status is not None:
        payload["status"] = status
    await member_cache.update_one(
        {"chat_id": chat_id, "user_id": user_id},
        {
            "$set": payload,
            "$setOnInsert": {
                "chat_id": chat_id,
                "user_id": user_id,
                "first_seen": when,
            },
        },
        upsert=True,
    )


async def find_latest_for_user(user_id: int) -> dict[str, Any] | None:
    """Return the most-recently-seen cache entry for ``user_id`` across all chats.

    Used by the cross-group identity resolver so logs can show a name/username
    even when Telegram's ``get_chat`` cannot reach the user (e.g. they have
    blocked the bot or never DM'd it).
    """
    cursor = member_cache.find({"user_id": user_id}).sort("last_seen", -1).limit(1)
    async for doc in cursor:
        return doc
    return None
