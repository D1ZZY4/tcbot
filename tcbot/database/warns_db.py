# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Warnings collection helpers - manages user warning records in groups."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from pymongo import ReturnDocument

from tcbot.database.documents import WarnCountDoc, WarnDoc
from tcbot.database.mongos import col, db_call
from tcbot.utils.time_and_date import utc_now

if TYPE_CHECKING:
    from motor.motor_asyncio import AsyncIOMotorCollection

log = logging.getLogger(__name__)

# ─────────────────────── Collection Helpers ─────────────────────── #
# * Internal collection access utilities for the warns database


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


# ──────────────────────────── Mutations ─────────────────────────── #
# * Functions that modify warning records in the database
# * Includes adding, removing, and clearing warnings
# ! CRITICAL: These functions modify per-chat warning counts


async def add_warn(user_id: int, reason: str, admin_id: int, chat_id: int) -> int:
    """Add a new warning to a user in a specific chat."""
    c = _warns()
    inserted = await db_call(
        c.insert_one(
            {
                "user_id": user_id,
                "reason": reason,
                "admin_id": admin_id,
                "chat_id": chat_id,
                "timestamp": utc_now(),
            }
        )
    )
    try:
        counter = await db_call(
            _warn_counts().find_one_and_update(
                _warn_key(user_id, chat_id),
                {
                    "$inc": {"count": 1},
                    "$set": {"updated_at": utc_now()},
                    "$setOnInsert": {
                        # * On insert the missing ``count`` field is treated
                        # * as zero by MongoDB; ``$inc`` then sets it to 1.
                        # * Do NOT add ``count: 0`` here -- it would conflict
                        # * with the ``$inc`` modifier and raise
                        # * ``OperationFailure: ConflictingUpdateOperators``
                        # * (MongoDB error code 40) on every first warn.
                        "user_id": user_id,
                        "chat_id": chat_id,
                    },
                },
                upsert=True,
                return_document=ReturnDocument.AFTER,
                projection={"_id": 0, "count": 1},
            )
        )
    except Exception:
        log.exception("add_warn counter update failed; rolling back warn insert")
        try:
            await db_call(c.delete_one({"_id": inserted.inserted_id}))
        except Exception as rollback_exc:
            log.warning(
                "add_warn rollback failed for inserted_id=%s: %s",
                inserted.inserted_id,
                rollback_exc,
            )
        raise
    if counter is None:
        return await _sync_warn_count(user_id, chat_id)
    return int(counter.get("count", 0))


# ─────────────────────── Queries & Retrieval ────────────────────── #
# * Functions to fetch warning data from the database
# * Includes counting, listing, and retrieving user warnings


async def warn_count(user_id: int, chat_id: int) -> int:
    """Get the current number of warnings for a user in a specific chat."""
    return await _sync_warn_count(user_id, chat_id)


async def clear_warns(user_id: int, chat_id: int) -> int:
    """Remove ALL warnings for a user in a specific chat.

    Raises the warns-delete failure instead of returning 0: a 0 return
    means "nothing to clear", and reporting an outage as an empty state
    would mislead the moderator. Counter-delete failures stay
    error-logged but non-fatal (the stale counter is flagged for repair
    while the requested clear itself succeeded).
    """
    key = _warn_key(user_id, chat_id)
    return await _clear_warn_docs(
        key,
        key,
        delete_all_counts=False,
        scope=f"clear_warns user={user_id} chat={chat_id}",
    )


async def clear_all_warns(user_id: int) -> int:
    """Remove ALL warnings for a user across every federation group.

    Used on federation auto-ban to ensure the user starts with a clean warn
    slate in every group after a potential unban, preventing immediate re-ban
    from stale per-group counts accumulated before the federation ban.

    Raises the warns-delete failure like :func:`clear_warns` (a 0 return
    means "nothing cleared"); callers running inside ``gather`` inspect the
    captured exception instead.
    """
    filt: dict[str, Any] = {"user_id": user_id}
    return await _clear_warn_docs(
        filt, filt, delete_all_counts=True, scope=f"clear_all_warns user={user_id}"
    )


async def _clear_warn_docs(
    warns_filter: dict[str, Any],
    counts_filter: dict[str, Any],
    *,
    delete_all_counts: bool,
    scope: str,
) -> int:
    """Delete warn history plus counter docs; shared by both clear paths.

    Returns the history deleted count. Raises the history-delete failure
    (a 0 return means "nothing to clear"); counter-delete failures are
    error-logged for operator repair while the clear itself succeeded.
    Cancellation propagates instead of reporting success.
    """
    warn_del, cnt_del = await asyncio.gather(
        db_call(_warns().delete_many(warns_filter)),
        db_call(
            _warn_counts().delete_many(counts_filter)
            if delete_all_counts
            else _warn_counts().delete_one(counts_filter)
        ),
        return_exceptions=True,
    )
    if isinstance(cnt_del, asyncio.CancelledError):
        raise cnt_del
    if isinstance(cnt_del, BaseException):
        # * Error-level: a surviving counter keeps stale counts that later
        # * warns increment from, so repair it instead of only logging.
        log.error("%s counter delete failed: %s", scope, cnt_del)
        await _repair_counter_delete(
            counts_filter, delete_all_counts=delete_all_counts, scope=scope
        )
    if isinstance(warn_del, BaseException):
        log.error("%s warns delete failed: %s", scope, warn_del)
        raise warn_del
    return warn_del.deleted_count


async def get_warns(
    user_id: int,
    chat_id: int,
    *,
    skip: int = 0,
    limit: int | None = None,
    newest_first: bool = False,
) -> list[WarnDoc]:
    """Return warn documents for a user in a chat, oldest first by default.

    Pass ``newest_first=True`` for paged newest-first views so page N
    holds the Nth-newest slice server-side; reversing an oldest-first
    page client-side would pin the newest records to the last pages.
    ``limit=None`` returns the full list (backwards compatible).
    """
    order: list[tuple[str, int]] = (
        [("timestamp", -1)] if newest_first else [("timestamp", 1)]
    )
    cursor = (
        _warns()
        .find(
            {"user_id": user_id, "chat_id": chat_id},
            {
                "_id": 0,
                "user_id": 1,
                "reason": 1,
                "admin_id": 1,
                "chat_id": 1,
                "timestamp": 1,
            },
            sort=order,
        )
        .skip(max(0, skip))
    )
    if limit is not None:
        cursor = cursor.limit(max(1, limit))
    return await db_call(cursor.to_list(limit))


async def remove_last_warn(user_id: int, chat_id: int) -> bool:
    """Delete the most recent warn document. Returns True if one was removed."""
    doc = await db_call(
        _warns().find_one(
            _warn_key(user_id, chat_id),
            {"_id": 1},
            sort=[("timestamp", -1), ("_id", -1)],
        )
    )
    if not doc:
        return False

    # Delete warn and update counter in parallel
    del_res, counter = await asyncio.gather(
        db_call(_warns().delete_one({"_id": doc["_id"]})),
        db_call(
            _warn_counts().find_one_and_update(
                {
                    **_warn_key(user_id, chat_id),
                    "count": {"$gt": 0},
                },
                {"$inc": {"count": -1}, "$set": {"updated_at": utc_now()}},
                return_document=ReturnDocument.AFTER,
                projection={"_id": 0, "count": 1},
            )
        ),
        return_exceptions=True,
    )

    if isinstance(del_res, asyncio.CancelledError):
        raise del_res
    if isinstance(del_res, BaseException):
        log.warning(
            "remove_last_warn delete failed for user=%d chat=%d: %s",
            user_id,
            chat_id,
            del_res,
        )
        await _recount_and_store(user_id, chat_id)
        return False
    if del_res.deleted_count == 0:
        await _recount_and_store(user_id, chat_id)
        return False

    if isinstance(counter, asyncio.CancelledError):
        raise counter
    if isinstance(counter, BaseException) or counter is None:
        await _recount_and_store(user_id, chat_id)
    return True


# ─────────────────────── Per-user history ───────────────────────── #


async def user_total_warns(user_id: int) -> int:
    """Total number of warning rows recorded against the user (all groups)."""
    return await db_call(_warns().count_documents({"user_id": user_id}))


async def user_warn_groups(user_id: int) -> list[tuple[int, int]]:
    """Return [(chat_id, count), ...] for every group where the user has warns, newest first."""
    docs = await db_call(
        _warn_counts()
        .find(
            {"user_id": user_id, "count": {"$gt": 0}},
            {"_id": 0, "chat_id": 1, "count": 1},
            sort=[("updated_at", -1)],
        )
        .to_list(length=None)
    )
    return [(int(d["chat_id"]), int(d["count"])) for d in docs]


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
