# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Pending-join request helpers."""

from __future__ import annotations

from tcbot.database.documents import PendingGroupDoc
from tcbot.database.mongos import db_call
from tcbot.utils.time_and_date import utc_now

from .collections import _pending


async def add_pending(chat_id: int, title: str, owner_id: int, message_id: int) -> None:
    """Add or update a pending join request from a group."""
    await db_call(
        _pending().update_one(
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
    )


async def get_pending(chat_id: int) -> PendingGroupDoc | None:
    """Get a pending join request by chat ID."""
    return await db_call(_pending().find_one({"chat_id": chat_id}))


async def remove_pending(chat_id: int) -> None:
    """Remove a pending join request after it's approved or rejected."""
    await db_call(_pending().delete_one({"chat_id": chat_id}))
