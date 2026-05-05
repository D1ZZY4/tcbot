# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
## Mute log helpers
from __future__ import annotations

from datetime import datetime, timezone

from tcbot.database.mongos import col


def _mutes():
    return col("mutes")


async def log_mute(user_id: int, chat_id: int, reason: str, admin_id: int) -> None:
    await _mutes().insert_one({
        "user_id": user_id,
        "chat_id": chat_id,
        "reason": reason,
        "admin_id": admin_id,
        "timestamp": datetime.now(timezone.utc),
    })
