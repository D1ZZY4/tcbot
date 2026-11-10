# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Warnings collection helpers - manages user warning records in groups."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Sequence

from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from tcbot.database._migration import _repoint_chat
from tcbot.database.documents import WarnCountDoc, WarnDoc
from tcbot.database.mongos import col, db_call
from tcbot.utils.dispatch import gather_bounded
from tcbot.utils.logger import get_logger
from tcbot.utils.time_and_date import utc_now

if TYPE_CHECKING:
    from pymongo.collection import Collection

log = get_logger(__name__)

# ──────────────────────────── Collection ─────────────────────────── #


def _warns() -> Collection:
    return col("warns")


def _warn_counts() -> Collection:
    return col("warn_counts")


def _warn_key(user_id: int, chat_id: int) -> dict[str, int]:
    return {"user_id": user_id, "chat_id": chat_id}


# ───────────────────────────── Counters ──────────────────────────── #


async def _inc_warn_count(user_id: int, chat_id: int) -> int | None:
    """Atomically increment the warn counter, retrying once on an upsert race.

    The ``(user_id, chat_id)`` unique index makes two concurrent first-warns
    race on the upsert insert: the loser raises ``DuplicateKeyError`` even
    though only the increment was lost. The winner's doc now exists, so one
    retry applies the same ``$inc`` to it and the count lands correctly; a
    second attempt cannot raise ``DuplicateKeyError`` again. Any other
    failure propagates unchanged so callers keep their own failure handling.
    Returns the updated count, or None when the server returns no document.
    """
    for attempt in range(2):
        try:
            counter = await db_call(
                lambda: _warn_counts().find_one_and_update(
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
        except DuplicateKeyError:
            if attempt == 0:
                # * Lost the insert race to a concurrent first-warn: the
                # * winner's doc now exists, so the retry increments it.
                continue
            raise
        if counter is None:
            return None
        return int(counter.get("count", 0))
    raise AssertionError("_inc_warn_count retry loop exhausted")  # unreachable


async def _sync_warn_count(user_id: int, chat_id: int) -> int:
    """Read the counter doc, or backfill it from warn history when missing.

    Uses an atomic ``find_one_and_update`` upsert so concurrent callers
    cannot double-backfill the same missing counter document: the loser of
    the insert race hits the unique index and raises ``DuplicateKeyError``,
    then re-reads the winner's count instead.
    """
    doc: WarnCountDoc | None = await db_call(
        lambda: _warn_counts().find_one(
            _warn_key(user_id, chat_id),
            {"_id": 0, "count": 1},
        )
    )
    if doc is not None:
        return int(doc.get("count", 0))

    count = await db_call(lambda: _warns().count_documents(_warn_key(user_id, chat_id)))
    if count > 0:
        try:
            updated = await db_call(
                lambda: _warn_counts().find_one_and_update(
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
        except DuplicateKeyError:
            # * A concurrent caller won the backfill insert; the doc exists
            # * now, so re-read the winner's count instead of failing.
            updated = await db_call(
                lambda: _warn_counts().find_one(
                    _warn_key(user_id, chat_id),
                    {"_id": 0, "count": 1},
                )
            )
        if updated is not None:
            return int(updated.get("count", count))
    return count


async def _store_warn_count(user_id: int, chat_id: int, count: int) -> None:
    """Persist the counter doc for a user/chat pair."""
    if count <= 0:
        await db_call(lambda: _warn_counts().delete_one(_warn_key(user_id, chat_id)))
        return
    await db_call(
        lambda: _warn_counts().update_one(
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
    count = await db_call(lambda: _warns().count_documents(_warn_key(user_id, chat_id)))
    await _store_warn_count(user_id, chat_id, count)


async def _repair_counter_delete(
    counts_filter: dict[str, Any],
    *,
    counts_many: bool,
    scope: str,
) -> None:
    """Best-effort repair after a counter-delete failure in _clear_warn_docs.

    A surviving counter keeps stale counts that later warns increment
    from, so the clear must not end with only a log line. Single-pair
    clears recount the pair (history is already gone, so the recount
    lands at zero and drops the stale doc); multi-pair clears retry the
    delete. The delete retry runs a bounded number of attempts with a
    short backoff; a persistent outage stays error-logged but non-fatal
    like the original delete failure so a clear never reports failure
    for a repair problem. Cancellation propagates.
    """
    if counts_many:
        for attempt in range(3):
            try:
                await db_call(
                    lambda: _warn_counts().delete_many(counts_filter), timeout=None
                )
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


# ────────────────────────────── Records ──────────────────────────── #


async def add_warn(user_id: int, reason: str, admin_id: int, chat_id: int) -> int:
    """Add a new warning to a user in a specific chat."""
    c = _warns()
    inserted = await db_call(
        lambda: c.insert_one(
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
        counter = await _inc_warn_count(user_id, chat_id)
    except Exception:
        log.exception("add_warn counter update failed; rolling back warn insert")
        try:
            await db_call(lambda: c.delete_one({"_id": inserted.inserted_id}))
        except Exception as rollback_exc:
            log.warning(
                "add_warn rollback failed for inserted_id=%s: %s",
                inserted.inserted_id,
                rollback_exc,
            )
        raise
    if counter is None:
        return await _sync_warn_count(user_id, chat_id)
    return counter


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
        counts_many=False,
        scope=f"clear_warns user={user_id} chat={chat_id}",
    )


async def clear_all_warns(user_id: int) -> int:
    """Remove ALL warnings for a user across every federation group.

    Used on federation threshold ban to ensure the user starts with a clean warn
    slate in every group after a potential unban, preventing immediate re-ban
    from stale per-group counts accumulated before the federation ban.

    Raises the warns-delete failure like :func:`clear_warns` (a 0 return
    means "nothing cleared"); callers running inside ``gather`` inspect the
    captured exception instead.
    """
    filt: dict[str, Any] = {"user_id": user_id}
    return await _clear_warn_docs(
        filt, filt, counts_many=True, scope=f"clear_all_warns user={user_id}"
    )


async def clear_warns_for_chats(user_id: int, chat_ids: Sequence[int]) -> int:
    """Remove the warnings of *user_id* in the given groups only.

    Used by a partially applied federation threshold ban: the groups where
    the ban landed lose their stale warn counts, while the groups where the
    enforcement failed keep theirs so the threshold can fire again there.
    Clearing everything would leave the failed groups with no warning and no
    ban.

    Raises the warns-delete failure like :func:`clear_warns`.
    """
    chats = [c for c in dict.fromkeys(chat_ids) if c]
    if not chats:
        return 0
    warns_filter: dict[str, Any] = {"user_id": user_id, "chat_id": {"$in": chats}}
    counts_filter: dict[str, Any] = {"user_id": user_id, "chat_id": {"$in": chats}}
    return await _clear_warn_docs(
        warns_filter,
        counts_filter,
        counts_many=True,
        scope=f"clear_warns_for_chats user={user_id} chats={len(chats)}",
    )


async def _clear_warn_docs(
    warns_filter: dict[str, Any],
    counts_filter: dict[str, Any],
    *,
    counts_many: bool,
    scope: str,
) -> int:
    """Delete warn history plus counter docs; shared by every clear path.

    Returns the history deleted count. Raises the history-delete failure
    (a 0 return means "nothing to clear"); counter-delete failures are
    error-logged for operator repair while the clear itself succeeded.
    Cancellation propagates instead of reporting success.
    """
    warn_del, cnt_del = await asyncio.gather(
        db_call(lambda: _warns().delete_many(warns_filter), timeout=None),
        db_call(
            lambda: (
                _warn_counts().delete_many(counts_filter)
                if counts_many
                else _warn_counts().delete_one(counts_filter)
            ),
            timeout=None,
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
            counts_filter, counts_many=counts_many, scope=scope
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
    return await db_call(lambda: list(cursor))


async def remove_last_warn(user_id: int, chat_id: int) -> bool:
    """Delete the most recent warn document. Returns True if one was removed."""
    doc = await db_call(
        lambda: _warns().find_one(
            _warn_key(user_id, chat_id),
            {"_id": 1},
            sort=[("timestamp", -1), ("_id", -1)],
        )
    )
    if not doc:
        return False

    # Delete warn and update counter in parallel
    del_res, counter = await asyncio.gather(
        db_call(lambda: _warns().delete_one({"_id": doc["_id"]})),
        db_call(
            lambda: _warn_counts().find_one_and_update(
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
        # * Fail closed like clear_warns: callers map False to "no
        # * warnings", so an outage must raise instead of reporting an
        # * empty state for a user that may still hold warns.
        log.error(
            "remove_last_warn delete failed for user=%d chat=%d: %s",
            user_id,
            chat_id,
            del_res,
        )
        await _recount_and_store(user_id, chat_id)
        raise del_res
    if del_res.deleted_count == 0:
        await _recount_and_store(user_id, chat_id)
        return False

    if isinstance(counter, asyncio.CancelledError):
        raise counter
    if isinstance(counter, BaseException) or counter is None:
        await _recount_and_store(user_id, chat_id)
    return True


async def user_total_warns(user_id: int) -> int:
    """Total number of warning rows recorded against the user (all groups)."""
    return await db_call(lambda: _warns().count_documents({"user_id": user_id}))


async def user_warn_groups(user_id: int) -> list[tuple[int, int]]:
    """Return [(chat_id, count), ...] for every group where the user has warns, newest first."""
    docs = await db_call(
        lambda: list(
            _warn_counts().find(
                {"user_id": user_id, "count": {"$gt": 0}},
                {"_id": 0, "chat_id": 1, "count": 1},
                sort=[("updated_at", -1)],
            )
        )
    )
    return [(int(d["chat_id"]), int(d["count"])) for d in docs]


# ───────────────────────────── Migration ─────────────────────────── #


async def migrate_records(old_chat_id: int, new_chat_id: int) -> bool:
    """Repoint every warn record and counter from ``old_chat_id`` to ``new_chat_id``.

    Called when a basic group migrates to a supergroup. Both ``warns`` (audit
    history) and ``warn_counts`` (the per-group counter documents that gate
    the threshold ban) are keyed by ``chat_id``, so without this the
    supergroup would silently start with a clean slate and lose all warning
    history from the legacy chat. Counter docs merge by summation: when the
    supergroup already holds warns, the counts add up instead of the blind
    ``$set`` overwriting one side or violating the per-pair unique index.
    Each old counter is consumed with an atomic take (removed before its
    count is added to the new pair), so a crash plus retry can only
    under-count, never double-count into a false threshold ban. Returns ``True``
    if any record was updated.
    """
    matched_any = await _repoint_chat(
        _warns(),
        old_chat_id,
        new_chat_id,
        log_msg="warns_db.migrate_records (%d -> %d) warns update failed",
    )
    try:
        old_counters = await db_call(
            lambda: list(
                _warn_counts().find(
                    {"chat_id": old_chat_id},
                    {"_id": 0, "user_id": 1, "count": 1},
                )
            )
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

    async def _merge_one_counter(doc: dict) -> bool:
        """Atomic-take one old counter and land its count on the new pair.

        Returns True when this user contributed to the migration. The old
        doc is gone before its count lands, so a crash plus retry cannot
        add it twice. Per-user failures log and return False; cancellation
        propagates via gather_bounded below.
        """
        uid = doc.get("user_id")
        cnt = int(doc.get("count", 0))
        if uid is None or cnt <= 0:
            return False
        try:
            taken = await db_call(
                lambda: _warn_counts().find_one_and_delete(
                    {"user_id": uid, "chat_id": old_chat_id}
                )
            )
            if taken is None:
                return False
            res = await db_call(
                lambda: _warn_counts().update_one(
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
            return res.matched_count > 0 or res.upserted_id is not None
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception(
                "warns_db.migrate_records (%d -> %d) counter merge failed for user=%s",
                old_chat_id,
                new_chat_id,
                uid,
            )
            return False

    # * Per-user takes are independent, so the merge round trips run
    # * concurrently under the shared database cap instead of one user at
    # * a time (a large legacy group could otherwise stall for hundreds
    # * of sequential trips).
    results = await gather_bounded([_merge_one_counter(doc) for doc in old_counters])
    matched_any = matched_any or any(r is True for r in results)
    try:
        await db_call(lambda: _warn_counts().delete_many({"chat_id": old_chat_id}))
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
    # * The aggregate scans every warn counter of the user; it is bounded by
    # * the user's own rows and stays inside the default call budget.
    result = await db_call(lambda: list(_warn_counts().aggregate(pipeline)))
    return int(result[0]["total"]) if result else 0


__all__ = [
    "_clear_warn_docs",
    "_inc_warn_count",
    "_recount_and_store",
    "_repair_counter_delete",
    "_store_warn_count",
    "_sync_warn_count",
    "_warn_counts",
    "_warn_key",
    "_warns",
    "add_warn",
    "clear_all_warns",
    "clear_warns",
    "clear_warns_for_chats",
    "federation_warn_count",
    "get_warns",
    "migrate_records",
    "remove_last_warn",
    "user_total_warns",
    "user_warn_groups",
    "warn_count",
]
