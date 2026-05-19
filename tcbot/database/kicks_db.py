# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""
Kick log helpers - tracks all kick events in groups
* Logs every time a user is kicked by an admin in any chat
* Stores basic metadata about the kick event for audit
"""

from __future__ import annotations

from datetime import datetime, timezone

from tcbot.database.mongos import col


# ─────────────────────── Collection Helpers ─────────────────────── #
# * Internal collection access utilities for the kicks database

def _kicks():
    """Get the kicks collection reference from MongoDB"""
    return col("kicks")


# ──────────────────────────── Mutations ─────────────────────────── #
# * Functions that create or modify kick log records
# * Used exclusively for audit logging of moderation actions

async def log_kick(user_id: int, chat_id: int, reason: str, admin_id: int) -> None:
    """
    Log a kick event to the database for audit purposes
    * Records who was kicked, in which chat, why, and who kicked them
    * Timestamps are stored in UTC for consistency across timezones
    * Creates a permanent record of the moderation action
    """
    await _kicks().insert_one({
        "user_id": user_id,
        "chat_id": chat_id,
        "reason": reason,
        "admin_id": admin_id,
        "timestamp": datetime.now(timezone.utc),
    })
