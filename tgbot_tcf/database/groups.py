# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""Repository functions for the ``federated_groups`` collection."""
from __future__ import annotations

from datetime import datetime
from typing import Any, AsyncIterator, Dict, List, Optional

from .mongo import federated_groups


async def find_by_id(chat_id: int) -> Optional[Dict[str, Any]]:
    """Return the federated-group record (active or not) for ``chat_id``."""
    return await federated_groups.find_one({"chat_id": chat_id})


async def find_active(chat_id: int) -> Optional[Dict[str, Any]]:
    """Return the federated-group record for ``chat_id`` only when active."""
    return await federated_groups.find_one({"chat_id": chat_id, "is_active": True})


async def upsert_active(
    *, chat_id: int, title: str, added_by: int, added_date: datetime
) -> None:
    """Insert or refresh an affiliated group, marking it active."""
    await federated_groups.update_one(
        {"chat_id": chat_id},
        {
            "$set": {
                "chat_id": chat_id,
                "title": title,
                "added_by": added_by,
                "added_date": added_date,
                "is_active": True,
            }
        },
        upsert=True,
    )


async def deactivate(chat_id: int) -> None:
    """Mark a group inactive (used by /detc, /rmtc, leave-all, cleanup)."""
    await federated_groups.update_one(
        {"chat_id": chat_id}, {"$set": {"is_active": False}}
    )


async def count_active() -> int:
    """Number of currently active affiliated groups."""
    return await federated_groups.count_documents({"is_active": True})


def iter_active() -> AsyncIterator[Dict[str, Any]]:
    """Async iterator over every active federated group."""
    return federated_groups.find({"is_active": True})


async def list_active() -> List[Dict[str, Any]]:
    """Return all active federated groups as a list (for paginated views)."""
    return [g async for g in iter_active()]
