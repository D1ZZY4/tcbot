# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Shared chat-repoint helper for basic-group to supergroup migrations."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from tcbot.database.mongos import db_call
from tcbot.utils.logger import get_logger

if TYPE_CHECKING:
    from motor.motor_asyncio import AsyncIOMotorCollection

log = get_logger(__name__)


async def _repoint_chat(
    collection: AsyncIOMotorCollection,
    old_chat_id: int,
    new_chat_id: int,
    *,
    log_msg: str,
) -> bool:
    """Repoint ``chat_id`` from ``old_chat_id`` to ``new_chat_id`` in one collection.

    Single owner for the migration repoint shared by kicks, mutes, and warns
    history: identical update, identical CancelledError handling, and the same
    matched-count return. Callers pass their own log message template (a
    ``%``-style format with the two chat ids as arguments) so operator log
    lines keep their per-domain wording. Cancellation propagates; any other
    failure is error-logged and reported as ``False``.
    """
    try:
        res = await db_call(
            collection.update_many(
                {"chat_id": old_chat_id},
                {"$set": {"chat_id": new_chat_id}},
            )
        )
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception(log_msg, old_chat_id, new_chat_id)
        return False
    return res.matched_count > 0
