# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Warn counter documents: atomic increments, backfill, and repair."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from pymongo import ReturnDocument

from tcbot.database.documents import WarnCountDoc
from tcbot.database.mongos import col, db_call
from tcbot.utils.logger import get_logger
from tcbot.utils.time_and_date import utc_now

if TYPE_CHECKING:
    from motor.motor_asyncio import AsyncIOMotorCollection

# * Logger keeps the pre-split name so log output is unchanged.
log = get_logger("tcbot.database.warns_db")


def _warns() -> AsyncIOMotorCollection:
    return col("warns")


def _warn_counts() -> AsyncIOMotorCollection:
    return col("warn_counts")


def _warn_key(user_id: int, chat_id: int) -> dict[str, int]:
    return {"user_id": user_id, "chat_id": chat_id}


async def _sync_warn_count(user_id: int, chat_id: int) -> int:
    """Read the counter doc, or backfill it from warn history when missing.

    Uses an atomic ``find_one_and_update`` upsert so concurrent callers cannot
    double-backfill the same missing counter document.
    """
    doc: WarnCountDoc | None = await db_call(
        _warn_counts().find_one(
            _warn_key(user_id, chat_id),
            {"_id": 0, "count": 1},
        )
    )
    if doc is not None:
        return int(doc.get("count", 0))

    count = await db_call(_warns().count_documents(_warn_key(user_id, chat_id)))
    if count > 0:
        # * Atomic upsert: only one concurrent caller wins the insert; others
        # * get the newly inserted doc back and re-read its count.
        updated = await db_call(
            _warn_counts().find_one_and_update(
                _warn_key(user_id, chat_id),
                {
                    "$setOnInsert": {
                        "user_id": user_id,
                        "chat_id": chat_id,
                        "count": count,
                        "updated_at": utc_now(),
                    },
                },
                upsert=True,
                return_document=ReturnDocument.AFTER,
                projection={"_id": 0, "count": 1},
            )
        )
        if updated is not None:
            return int(updated.get("count", count))
    return count


async def _store_warn_count(user_id: int, chat_id: int, count: int) -> None:
    """Persist the counter doc for a user/chat pair."""
    if count <= 0:
        await db_call(_warn_counts().delete_one(_warn_key(user_id, chat_id)))
        return
    await db_call(
        _warn_counts().update_one(
            _warn_key(user_id, chat_id),
            {
                "$set": {
                    "count": count,
                    "updated_at": utc_now(),
                },
                "$setOnInsert": {
                    "user_id": user_id,
                    "chat_id": chat_id,
                },
            },
            upsert=True,
        )
    )


async def _recount_and_store(user_id: int, chat_id: int) -> None:
    """Rebuild the counter from warn history after a failed atomic update.

    Single owner for the repair path shared by every counter-write failure
    below, so a fix to the recount logic cannot drift between call sites.
    """
    count = await db_call(_warns().count_documents(_warn_key(user_id, chat_id)))
    await _store_warn_count(user_id, chat_id, count)


async def _repair_counter_delete(
    counts_filter: dict[str, Any],
    *,
    delete_all_counts: bool,
    scope: str,
) -> None:
    """Best-effort repair after a counter-delete failure in _clear_warn_docs.

    A surviving counter keeps stale counts that later warns increment
    from, so the clear must not end with only a log line. Single-chat
    clears recount the pair (history is already gone, so the recount
    lands at zero and drops the stale doc); federation-wide clears retry
    the delete. The delete retry runs a bounded number of attempts with a
    short backoff; a persistent outage stays error-logged but non-fatal
    like the original delete failure so a clear never reports failure
    for a repair problem. Cancellation propagates.
    """
    if delete_all_counts:
        for attempt in range(3):
            try:
                await db_call(_warn_counts().delete_many(counts_filter))
                return
            except asyncio.CancelledError:
                raise
            except Exception:
                if attempt == 2:
                    log.exception("%s counter repair failed", scope)
                else:
                    await asyncio.sleep(0.5 * (attempt + 1))
        return
    try:
        await _recount_and_store(
            int(counts_filter["user_id"]), int(counts_filter["chat_id"])
        )
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("%s counter repair failed", scope)


async def warn_count(user_id: int, chat_id: int) -> int:
    """Get the current number of warnings for a user in a specific chat."""
    return await _sync_warn_count(user_id, chat_id)
