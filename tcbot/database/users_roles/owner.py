# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Owner CRUD for the federation founder record."""

from __future__ import annotations

import asyncio
from typing import cast

from pymongo.errors import DuplicateKeyError

from tcbot.database.cache import (
    _OWNER_KEY,
    effective_role_cache,
    owner_id_cache,
)
from tcbot.database.documents import AdminDoc
from tcbot.database.mongos import col, db_call
from tcbot.utils.logger import get_logger

# * Logger keeps the pre-split name so log output is unchanged.
log = get_logger("tcbot.database.users_roles")


async def get_owner_id(*, fresh: bool = False) -> int | None:
    """Return the current owner's user ID (L1->L2->DB cached).

    With ``fresh=True`` the cache is bypassed and the row is read directly
    from MongoDB, then the cache is refreshed. Enforcement decisions use
    ``fresh=True`` so a transfer in another process is never hidden for
    up to the 300 s owner TTL; display reads keep the cached fast path.
    """

    async def _fetch() -> int | None:
        doc: AdminDoc | None = await db_call(
            col("tc_owners").find_one(
                {}, {"_id": 0, "user_id": 1}, sort=[("user_id", 1)]
            )
        )
        return doc["user_id"] if doc else None

    if fresh:
        owner = await _fetch()
        owner_id_cache.put(_OWNER_KEY, owner)
        return owner
    return cast("int | None", await owner_id_cache.get_or_fetch(_OWNER_KEY, _fetch))


async def is_owner(user_id: int) -> bool:
    """Return True if user_id belongs to the bot owner.

    Served from the cached owner ID (300 s L1 TTL, invalidated on
    transfer) instead of a dedicated ``find_one`` so hot auth paths pay
    zero MongoDB round trips on cache hits. Errors propagate like the
    previous direct read so decorators keep their fail-closed retry reply.
    """
    return (await get_owner_id()) == user_id


async def ensure_initial_owner(initial_id: int) -> None:
    """Create the first owner entry if the owners collection is empty."""
    if await db_call(col("tc_owners").estimated_document_count()) > 0:
        return
    try:
        await db_call(col("tc_owners").insert_one({"user_id": initial_id}))
        owner_id_cache.put(_OWNER_KEY, initial_id)
    except DuplicateKeyError:
        # * Another instance won the startup race; drop the cache so the next read refreshes.
        owner_id_cache.invalidate(_OWNER_KEY)


async def set_owner(user_id: int) -> None:
    """Replace the current owner with user_id; clears the role cache."""
    # * Single upsert write: find_one_and_replace on an empty filter inserts
    # * when the collection is empty and replaces the lowest-id row
    # * otherwise, so a mid-flight crash can never leave zero owner rows
    # * (the old insert-then-delete pair could). A leftover second row from
    # * an earlier split brain is still removed below for convergence; the
    # * delete retries briefly so a transient failure cannot strand two
    # * owner rows without operator guidance.
    await db_call(
        col("tc_owners").find_one_and_replace(
            {},
            {"user_id": user_id},
            upsert=True,
            sort=[("user_id", 1)],
        )
    )
    # * Convergence delete with a bounded retry: a transient failure backs
    # * off and retries (three attempts total), while a persistent failure
    # * logs operator guidance and still raises so the transfer fails closed
    # * exactly as before. Cancellation propagates immediately.
    for attempt in range(3):
        try:
            await db_call(col("tc_owners").delete_many({"user_id": {"$ne": user_id}}))
            break
        except asyncio.CancelledError:
            raise
        except Exception:
            if attempt < 2:
                await asyncio.sleep(0.5 * (attempt + 1))
                continue
            log.exception(
                "set_owner cleanup delete failed for user %d: tc_owners may "
                "still hold two owner rows (split brain). Owner resolution "
                "picks the lowest user_id, so the previous Founder can be "
                "left without founder or admin role. Inspect the tc_owners "
                "collection and delete the row whose user_id != %d manually, "
                "then retry the transfer.",
                user_id,
                user_id,
            )
            raise
    owner_id_cache.put(_OWNER_KEY, user_id)
    # * The two writes above are not atomic: a crash between them can leave
    # * one or two owner rows (never zero; the first write upserts). Verify
    # * the invariant and log loudly so a split brain is noticed instead of
    # * serving nondeterministic owners.
    try:
        owner_rows = await db_call(col("tc_owners").estimated_document_count())
    except Exception:
        log.exception("set_owner verification read failed for user %d", user_id)
    else:
        if owner_rows != 1:
            log.error(
                "set_owner left %d owner rows for user %d; expected exactly 1.",
                owner_rows,
                user_id,
            )
    # * Full two-layer invalidation: old owner's ID is unknown, so we cannot
    # * call invalidate(old_id).  clear_all() sweeps L1 + all Redis keys with
    # * the "role" prefix so no process reads a stale "founder" role after the
    # * transfer completes.
    await effective_role_cache.clear_all()
