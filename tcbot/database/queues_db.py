# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""
Promotion request queue - manages promotion request queue for staff applications
* Handles enqueuing, resolving, and retrieving pending promotion requests
* Uses MongoDB's promotion_requests collection to store all request data
"""

from __future__ import annotations

from tcbot.database.documents import PromotionRequestDoc
from tcbot.database.mongos import col, make_short_id
from tcbot.utils.timedate_format import utc_now

# ─────────────────────── Collection Helpers ─────────────────────── #
# * Internal collection access and ID generation utilities


def _requests():
    """Get the promotion_requests collection reference from MongoDB"""
    return col("promotion_requests")


def _new_request_id() -> str:
    """Generate a unique short ID for new promotion requests"""
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
    """
    Add a new promotion request to the queue
    * Generates a unique request ID for the new entry
    * Initializes all metadata fields with default values
    * Returns the generated request_id for future reference
    """
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
    """
    Get a promotion request by its unique request ID
    * Returns the full request document including all metadata
    """
    return await _requests().find_one({"request_id": request_id})


async def get_request(user_id: int) -> PromotionRequestDoc | None:
    """
    Get the pending request for a specific user
    * Only returns requests that are still in "pending" status
    """
    return await _requests().find_one({"target_id": user_id, "status": "pending"})


async def all_pending() -> list[PromotionRequestDoc]:
    """
    Get all currently pending promotion requests
    * Returns full documents for all unresolved requests
    """
    return await _requests().find({"status": "pending"}).to_list(None)


async def resolve(request_id: str, status: str, resolved_by: int) -> None:
    """
    Mark a pending promotion request as resolved
    * Sets resolution status, timestamp, and the admin who resolved it
    * Changes status from "pending" to approved/rejected
    """
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
    """
    Count the number of pending promotion requests
    * Uses efficient count_documents for fast retrieval
    """
    return await _requests().count_documents({"status": "pending"})
