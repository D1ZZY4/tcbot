# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
## Bans collection helpers
from __future__ import annotations

from datetime import datetime, timezone

from tcbot.database.mongos import col, make_short_id


def _bans():
    return col("bans")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def make_ban_id() -> str:
    return make_short_id()


async def get_active_ban(user_id: int) -> dict | None:
    return await _bans().find_one({"banned_user_id": user_id, "is_active": True})


async def get_ban(ban_id: str) -> dict | None:
    return await _bans().find_one({"ban_id": ban_id})


async def create_ban(
    target_id: int,
    reason: str,
    admin_id: int,
    proof_msg_id: int,
    log_msg_id: int,
    ban_id: str | None = None,
) -> dict:
    if ban_id is None:
        ban_id = make_ban_id()
    doc = {
        "ban_id": ban_id,
        "banned_user_id": target_id,
        "reason": reason,
        "admin_user_id": admin_id,
        "proof_message_id": proof_msg_id,
        "log_message_id": log_msg_id,
        "previous_proof_message_id": None,
        "previous_log_message_id": None,
        "timestamp": _now(),
        "updated_timestamp": None,
        "is_active": True,
        "update_count": 0,
        "review_message_id": None,
        "review_timestamp": None,
    }
    await _bans().insert_one(doc)
    return doc


async def update_ban(
    ban_id: str,
    reason: str,
    admin_id: int,
    new_proof_id: int,
    new_log_id: int = 0,
    old_proof_id: int = 0,
    old_log_id: int = 0,
) -> dict | None:
    return await _bans().find_one_and_update(
        {"ban_id": ban_id},
        {
            "$set": {
                "reason": reason,
                "admin_user_id": admin_id,
                "proof_message_id": new_proof_id,
                "log_message_id": new_log_id,
                "previous_proof_message_id": old_proof_id,
                "previous_log_message_id": old_log_id,
                "updated_timestamp": _now(),
            },
            "$inc": {"update_count": 1},
        },
        return_document=True,
    )


async def set_log_message_id(ban_id: str, log_msg_id: int) -> None:
    await _bans().update_one(
        {"ban_id": ban_id},
        {"$set": {"log_message_id": log_msg_id}},
    )


async def deactivate_ban(ban_id: str) -> bool:
    r = await _bans().update_one({"ban_id": ban_id}, {"$set": {"is_active": False}})
    return r.modified_count > 0


async def set_review(ban_id: str, msg_id: int) -> None:
    await _bans().update_one(
        {"ban_id": ban_id},
        {"$set": {"review_message_id": msg_id, "review_timestamp": _now()}},
    )


async def set_appeal_log_msg(
    ban_id: str,
    msg_id: int,
    submitted_at: datetime | None = None,
    appeal_link: str = "",
) -> None:
    await _bans().update_one(
        {"ban_id": ban_id},
        {"$set": {
            "appeal_log_msg_id": msg_id,
            "appeal_submitted_at": submitted_at or _now(),
            "appeal_link": appeal_link,
        }},
    )


async def active_ban_count() -> int:
    return await _bans().count_documents({"is_active": True})


async def active_bans() -> list[dict]:
    return await _bans().find({"is_active": True}).to_list(None)


async def active_ban_user_ids() -> list[int]:
    """Return only the user IDs of all active bans (projection-only, fastest path)."""
    docs = await _bans().find(
        {"is_active": True}, {"_id": 0, "banned_user_id": 1}
    ).to_list(None)
    return [doc["banned_user_id"] for doc in docs]
