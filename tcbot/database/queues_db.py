# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Promotion request queue - manages promotion request queue for staff applications."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pymongo.errors import DuplicateKeyError

from tcbot.database.documents import PromotionRequestDoc, RequestStatus
from tcbot.database.mongos import col, db_call, make_short_id
from tcbot.utils.time_and_date import utc_now

if TYPE_CHECKING:
    from motor.motor_asyncio import AsyncIOMotorCollection

# ─────────────────────── Collection Helpers ─────────────────────── #
# * Internal collection access and ID generation utilities


def _requests() -> AsyncIOMotorCollection:
    return col("promotion_requests")


# ──────────────────────────── Mutations ─────────────────────────── #
# * Functions that create or modify promotion request records
# * Manages the queue's state for pending and resolved requests


class AlreadyPendingError(DuplicateKeyError):
    """Target already has a pending promotion request.

    Subclasses DuplicateKeyError so callers checking for DuplicateKeyError
    keep working without changes.
    """


def _is_pending_violation(exc: DuplicateKeyError) -> bool:
    """Return True when exc came from the one-pending-per-user partial index.

    The partial unique index is on target_id (see ensure_indexes) while the
    random-ID unique index is on request_id, so keyPattern tells them apart.
    Falls back to the server message which names the index. Unknown shapes
    return False to keep the legacy retry path.
    """
    details = exc.details or {}
    pattern = details.get("keyPattern")
    if isinstance(pattern, dict):
        if "target_id" in pattern:
            return True
        if "request_id" in pattern:
            return False
    message = str(exc)
    if "target_id" in message:
        return True
    if "request_id" in message:
        return False
    return False


async def enqueue(
    user_id: int,
    username: str | None,
    first_name: str,
    promoted_by: int,
) -> str:
    """Add a new promotion request to the queue.

    Retries once with a fresh ID only for genuine request_id collisions
    (mirrors ``bans_db.create_ban``). A partial-unique pending rejection
    raises AlreadyPendingError at once without burning the retry.
    """

    async def _insert(request_id: str) -> None:
        await db_call(
            _requests().insert_one(
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
        )

    request_id = make_short_id()
    try:
        await _insert(request_id)
    except DuplicateKeyError as exc:
        if _is_pending_violation(exc):
            raise AlreadyPendingError(str(exc), exc.code, exc.details) from exc
        request_id = make_short_id()
        try:
            await _insert(request_id)
        except DuplicateKeyError as retry_exc:
            if _is_pending_violation(retry_exc):
                raise AlreadyPendingError(
                    str(retry_exc), retry_exc.code, retry_exc.details
                ) from retry_exc
            raise
    return request_id


# ───────────────────────────── Queries ──────────────────────────── #
# * Functions to retrieve promotion request data from the database
# * Includes lookups by ID, user, and counts of pending requests


async def get_request_by_id(request_id: str) -> PromotionRequestDoc | None:
    """Get a promotion request by its unique request ID."""
    return await db_call(_requests().find_one({"request_id": request_id}))


async def get_request(user_id: int) -> PromotionRequestDoc | None:
    """Get the pending request for a specific user."""
    return await db_call(
        _requests().find_one({"target_id": user_id, "status": "pending"})
    )


async def all_pending() -> list[PromotionRequestDoc]:
    """Get all currently pending promotion requests, oldest first."""
    return await db_call(
        _requests()
        .find(
            {"status": "pending"},
            {
                "_id": 0,
                "request_id": 1,
                "target_id": 1,
                "username": 1,
                "first_name": 1,
                "requested_date": 1,
            },
            sort=[("requested_date", 1)],
        )
        .to_list(200)
    )


# * Total pending count for list headers. Kept byte-identical to
# * all_pending's status filter so "shown vs total" arithmetic in the
# * promote-list header stays meaningful.
async def pending_count() -> int:
    """Count all currently pending promotion requests."""
    return await db_call(_requests().count_documents({"status": "pending"}))


async def resolve(request_id: str, status: RequestStatus, resolved_by: int) -> bool:
    """Mark a pending promotion request as resolved.

    The ``pending`` filter makes the claim atomic: concurrent decisions on
    the same request resolve exactly once, and late taps get ``False``.
    """
    # ! Only terminal states may be stored: an arbitrary string here would
    # ! break the pending filters every other helper relies on.
    if status not in ("approved", "rejected"):
        raise ValueError(f"Refusing to resolve promotion request to {status!r}")
    result = await db_call(
        _requests().update_one(
            {"request_id": request_id, "status": "pending"},
            {
                "$set": {
                    "status": status,
                    "resolved_date": utc_now(),
                    "resolved_by": resolved_by,
                }
            },
        )
    )
    return result.modified_count > 0
