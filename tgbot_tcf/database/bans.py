# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""Repository functions for the ``bans`` collection.

Every read or write against an individual ban document goes through one of
the helpers below so that field names and update shapes live in a single
place. The schema is defined in PROMPT (see DATABASE SCHEMA section).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from .mongo import bans


async def find_active_for_user(user_id: int) -> Optional[Dict[str, Any]]:
    """Return the currently active ban for ``user_id`` (or ``None``)."""
    return await bans.find_one({"banned_user_id": user_id, "is_active": True})


async def find_by_ban_id(ban_id: str) -> Optional[Dict[str, Any]]:
    """Return the ban with ``ban_id`` regardless of its active state."""
    return await bans.find_one({"ban_id": ban_id})


async def insert_new(
    *,
    ban_id: str,
    banned_user_id: int,
    reason: str,
    admin_user_id: int,
    proof_message_id: int,
    log_message_id: Optional[int],
    timestamp: datetime,
) -> None:
    """Insert a brand-new ban document with the canonical schema."""
    await bans.insert_one(
        {
            "ban_id": ban_id,
            "banned_user_id": banned_user_id,
            "reason": reason,
            "admin_user_id": admin_user_id,
            "proof_message_id": proof_message_id,
            "log_message_id": log_message_id,
            "previous_proof_message_id": None,
            "previous_log_message_id": None,
            "timestamp": timestamp,
            "updated_timestamp": None,
            "is_active": True,
            "update_count": 0,
            "review_message_id": None,
            "review_timestamp": None,
        }
    )


async def update_existing(
    *,
    ban_id: str,
    previous_proof_message_id: Optional[int],
    previous_log_message_id: Optional[int],
    proof_message_id: int,
    log_message_id: Optional[int],
    admin_user_id: int,
    reason: str,
    update_timestamp: datetime,
) -> None:
    """Apply the PROMPT-mandated update shape to an existing ban."""
    await bans.update_one(
        {"ban_id": ban_id},
        {
            "$set": {
                "previous_proof_message_id": previous_proof_message_id,
                "previous_log_message_id": previous_log_message_id,
                "proof_message_id": proof_message_id,
                "log_message_id": log_message_id,
                "admin_user_id": admin_user_id,
                "reason": reason,
                "updated_timestamp": update_timestamp,
            },
            "$inc": {"update_count": 1},
        },
    )


async def deactivate(ban_id: str) -> None:
    """Mark the ban inactive without removing the historical record."""
    await bans.update_one({"ban_id": ban_id}, {"$set": {"is_active": False}})


async def attach_review(
    *, ban_id: str, review_message_id: int, review_timestamp: datetime
) -> None:
    """Persist appeal-review metadata so the 12-hour rule can be enforced."""
    await bans.update_one(
        {"ban_id": ban_id},
        {
            "$set": {
                "review_message_id": review_message_id,
                "review_timestamp": review_timestamp,
            }
        },
    )


async def attach_appeal_log_message(
    *, ban_id: str, appeal_log_message_id: int
) -> None:
    """Remember the channel message id of the 'New Appeal Submitted' log post.

    The id is reused on approve/reject to edit the existing log message in
    place rather than spamming the channel with a new one.
    """
    await bans.update_one(
        {"ban_id": ban_id},
        {"$set": {"appeal_log_message_id": appeal_log_message_id}},
    )


async def count_active() -> int:
    """Number of currently active bans."""
    return await bans.count_documents({"is_active": True})
