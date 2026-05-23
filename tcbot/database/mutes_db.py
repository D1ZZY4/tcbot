# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""Mute log helpers - tracks all mute events in groups."""

from __future__ import annotations

from tcbot.database.mongos import col
from tcbot.utils.timedate_format import utc_now

# ─────────────────────── Collection Helpers ─────────────────────── #
# * Internal collection access utilities for the mutes database


def _mutes():
    return col("mutes")


# ──────────────────────────── Mutations ─────────────────────────── #
# * Functions that create or modify mute log records
# * Primarily used for audit logging of moderation actions


async def log_mute(user_id: int, chat_id: int, reason: str, admin_id: int) -> None:
    """Log a mute event to the database for audit purposes."""
    await _mutes().insert_one(
        {
            "user_id": user_id,
            "chat_id": chat_id,
            "reason": reason,
            "admin_id": admin_id,
            "timestamp": utc_now(),
        }
    )
