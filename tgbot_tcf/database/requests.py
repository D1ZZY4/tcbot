# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""Repository helpers for the ``promotion_requests`` collection."""
from __future__ import annotations

from datetime import datetime
from typing import Any, AsyncIterator, Dict, List, Optional

from .mongo import promotion_requests


async def create(
    *, request_id: str, target_id: int, promoted_by: int, requested_date: datetime
) -> None:
    """Persist a fresh pending promotion request."""
    await promotion_requests.insert_one(
        {
            "request_id": request_id,
            "target_id": target_id,
            "promoted_by": promoted_by,
            "status": "pending",
            "requested_date": requested_date,
            "resolved_date": None,
            "resolved_by": None,
        }
    )


async def find_by_id(request_id: str) -> Optional[Dict[str, Any]]:
    return await promotion_requests.find_one({"request_id": request_id})


async def list_pending() -> List[Dict[str, Any]]:
    cursor = promotion_requests.find({"status": "pending"})
    return [r async for r in cursor]


async def resolve(
    *, request_id: str, status: str, resolved_by: int, resolved_date: datetime
) -> None:
    """Mark a request as ``approved`` or ``rejected``."""
    await promotion_requests.update_one(
        {"request_id": request_id},
        {
            "$set": {
                "status": status,
                "resolved_date": resolved_date,
                "resolved_by": resolved_by,
            }
        },
    )


def iter_pending() -> AsyncIterator[Dict[str, Any]]:
    return promotion_requests.find({"status": "pending"})
