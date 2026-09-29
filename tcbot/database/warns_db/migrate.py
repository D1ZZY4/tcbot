# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Warn migration and federation-wide warn totals."""

from __future__ import annotations

import asyncio

from tcbot.database.mongos import db_call
from tcbot.utils.logger import get_logger
from tcbot.utils.time_and_date import utc_now

from .counters import _warn_counts, _warns

# * Logger keeps the pre-split name so log output is unchanged.
log = get_logger("tcbot.database.warns_db")


async def migrate_records(old_chat_id: int, new_chat_id: int) -> bool:
    """Repoint every warn record and counter from ``old_chat_id`` to ``new_chat_id``.

    Called when a basic group migrates to a supergroup. Both ``warns`` (audit
    history) and ``warn_counts`` (the per-group counter documents that gate
    the auto-ban threshold) are keyed by ``chat_id``, so without this the
    supergroup would silently start with a clean slate and lose all warning
    history from the legacy chat. Counter docs merge by summation: when the
    supergroup already holds warns, the counts add up instead of the blind
    ``$set`` overwriting one side or violating the per-pair unique index.
    Each old counter is consumed with an atomic take (removed before its
    count is added to the new pair), so a crash plus retry can only
    under-count, never double-count into a false auto-ban. Returns ``True``
    if any record was updated.
    """
    try:
        warns_r = await db_call(
            _warns().update_many(
                {"chat_id": old_chat_id},
                {"$set": {"chat_id": new_chat_id}},
            )
        )
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception(
            "warns_db.migrate_records (%d -> %d) warns update failed",
            old_chat_id,
            new_chat_id,
        )
        return False
    matched_any = warns_r.matched_count > 0
    try:
        old_counters = await db_call(
            _warn_counts()
            .find(
                {"chat_id": old_chat_id},
                {"_id": 0, "user_id": 1, "count": 1},
            )
            .to_list(None)
        )
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception(
            "warns_db.migrate_records (%d -> %d) counter read failed",
            old_chat_id,
            new_chat_id,
        )
        return matched_any
    for doc in old_counters:
        uid = doc.get("user_id")
        cnt = int(doc.get("count", 0))
        if uid is None or cnt <= 0:
            continue
        try:
            # * Atomic take: the old doc is gone before its count lands on
            # * the new pair, so a crash plus retry cannot add it twice.
            taken = await db_call(
                _warn_counts().find_one_and_delete(
                    {"user_id": uid, "chat_id": old_chat_id}
                )
            )
            if taken is None:
                continue
            res = await db_call(
                _warn_counts().update_one(
                    {"user_id": uid, "chat_id": new_chat_id},
                    {
                        "$inc": {"count": cnt},
                        "$set": {"updated_at": utc_now()},
                        "$setOnInsert": {
                            "user_id": uid,
                            "chat_id": new_chat_id,
                        },
                    },
                    upsert=True,
                )
            )
            if res.matched_count > 0 or res.upserted_id is not None:
                matched_any = True
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception(
                "warns_db.migrate_records (%d -> %d) counter merge failed for user=%s",
                old_chat_id,
                new_chat_id,
                uid,
            )
    try:
        await db_call(_warn_counts().delete_many({"chat_id": old_chat_id}))
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception(
            "warns_db.migrate_records (%d -> %d) stale counter cleanup failed",
            old_chat_id,
            new_chat_id,
        )
    return matched_any


async def federation_warn_count(user_id: int) -> int:
    """Total active warn count for a user across all federation chats.

    Sums ``count`` across all ``warn_counts`` documents for the user via a
    server-side ``$group`` aggregation, avoiding a Python-side sum over a
    potentially large result set.  Returns 0 when the user has no active
    warnings.
    """
    pipeline = [
        {"$match": {"user_id": user_id, "count": {"$gt": 0}}},
        {"$group": {"_id": None, "total": {"$sum": "$count"}}},
    ]
    result = await db_call(_warn_counts().aggregate(pipeline).to_list(length=1))
    return int(result[0]["total"]) if result else 0
