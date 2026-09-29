# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Warn records: add, clear, list, and trim operations."""

from __future__ import annotations

import asyncio
from typing import Any

from pymongo import ReturnDocument

from tcbot.database.documents import WarnDoc
from tcbot.database.mongos import db_call
from tcbot.utils.logger import get_logger
from tcbot.utils.time_and_date import utc_now

from .counters import (
    _recount_and_store,
    _repair_counter_delete,
    _sync_warn_count,
    _warn_counts,
    _warn_key,
    _warns,
)

# * Logger keeps the pre-split name so log output is unchanged.
log = get_logger("tcbot.database.warns_db")


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
