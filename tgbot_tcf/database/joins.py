# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""Repository helpers for ``pending_joins`` (PROMPT Feature 1 step 5)."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from .mongo import pending_joins


async def upsert(
    *,
    chat_id: int,
    title: str,
    requested_by: int,
    requested_at: datetime,
    notice_message_id: Optional[int],
) -> None:
    """Park an affiliation request that is waiting for admin permissions."""
    await pending_joins.update_one(
        {"chat_id": chat_id},
        {
            "$set": {
                "chat_id": chat_id,
                "title": title,
                "requested_by": requested_by,
                "requested_at": requested_at,
                "notice_message_id": notice_message_id,
            }
        },
        upsert=True,
    )


async def get(chat_id: int) -> Optional[Dict[str, Any]]:
    return await pending_joins.find_one({"chat_id": chat_id})


async def delete(chat_id: int) -> None:
    await pending_joins.delete_one({"chat_id": chat_id})
