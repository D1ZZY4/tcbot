# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Studio

"""Promotion request queue - manages promotion request queue for staff applications."""

from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorCollection

from tcbot.database.documents import PromotionRequestDoc
from tcbot.database.mongos import col, make_short_id
from tcbot.utils.timedate_format import utc_now

# ─────────────────────── Collection Helpers ─────────────────────── #
# * Internal collection access and ID generation utilities


def _requests() -> AsyncIOMotorCollection:
    return col("promotion_requests")


def _new_request_id() -> str:
    return make_short_id()


# ──────────────────────────── Mutations ─────────────────────────── #
# * Functions that create or modify promotion request records
# * Manages the queue's state for pending and resolved requests


async def enqueue(
    user_id: int,
    username: str | None,
    first_name: str,
    promoted_by: int,
) -> str:
    """Add a new promotion request to the queue."""
    request_id = _new_request_id()
    await _requests().insert_one(
        {
            "request_id": request_id,
            "target_id": user_id,
            "username": username,
            "first_name": first_name,
            "promoted_by": promoted_by,
            "status": "pending",
            "requested_date": utc_now(),
            "resolved_date": None,
            "resolved_by": None,
        }
    )
    return request_id


# ───────────────────────────── Queries ──────────────────────────── #
# * Functions to retrieve promotion request data from the database
# * Includes lookups by ID, user, and counts of pending requests


async def get_request_by_id(request_id: str) -> PromotionRequestDoc | None:
    """Get a promotion request by its unique request ID."""
    return await _requests().find_one({"request_id": request_id})


async def get_request(user_id: int) -> PromotionRequestDoc | None:
    """Get the pending request for a specific user."""
    return await _requests().find_one({"target_id": user_id, "status": "pending"})


async def all_pending() -> list[PromotionRequestDoc]:
    """Get all currently pending promotion requests."""
    return await _requests().find({"status": "pending"}).to_list(None)


async def resolve(request_id: str, status: str, resolved_by: int) -> None:
    """Mark a pending promotion request as resolved."""
    await _requests().update_one(
        {"request_id": request_id},
        {
            "$set": {
                "status": status,
                "resolved_date": utc_now(),
                "resolved_by": resolved_by,
            }
        },
    )


async def pending_count() -> int:
    """Count the number of pending promotion requests."""
    return await _requests().count_documents({"status": "pending"})
