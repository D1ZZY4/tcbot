# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
## Promotion request queue – collection: promotion_requests
from __future__ import annotations

from datetime import datetime, timezone

from tcbot.database.mongos import col, make_short_id


def _requests():
    return col("promotion_requests")


def _new_request_id() -> str:
    return make_short_id()


async def enqueue(
    user_id: int,
    username: str | None,
    first_name: str,
    promoted_by: int,
) -> str:
    request_id = _new_request_id()
    await _requests().insert_one({
        "request_id": request_id,
        "target_id": user_id,
        "username": username,
        "first_name": first_name,
        "promoted_by": promoted_by,
        "status": "pending",
        "requested_date": datetime.now(timezone.utc),
        "resolved_date": None,
        "resolved_by": None,
    })
    return request_id


async def get_request_by_id(request_id: str) -> dict | None:
    return await _requests().find_one({"request_id": request_id})


async def get_request(user_id: int) -> dict | None:
    return await _requests().find_one({"target_id": user_id, "status": "pending"})


async def all_pending() -> list[dict]:
    return await _requests().find({"status": "pending"}).to_list(None)


async def resolve(request_id: str, status: str, resolved_by: int) -> None:
    await _requests().update_one(
        {"request_id": request_id},
        {"$set": {
            "status": status,
            "resolved_date": datetime.now(timezone.utc),
            "resolved_by": resolved_by,
        }},
    )


async def pending_count() -> int:
    return await _requests().count_documents({"status": "pending"})
