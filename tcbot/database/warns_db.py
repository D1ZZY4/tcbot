# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Warnings collection helpers - manages user warning records in groups."""

from __future__ import annotations

import asyncio
from itertools import batched
from typing import TYPE_CHECKING, Any, cast

from sqlalchemy import and_, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from tcbot.database.base import warn_counts, warns
from tcbot.database.documents import WarnCountDoc, WarnDoc
from tcbot.database.engine import (
    db_call,
    fetch_all,
    fetch_one,
    fetch_value,
    run,
    run_returning,
    run_transaction,
)
from tcbot.utils.dispatch import gather_bounded
from tcbot.utils.logger import get_logger
from tcbot.utils.time_and_date import utc_now

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy import ColumnElement, Table
    from sqlalchemy.engine import CursorResult
    from sqlalchemy.ext.asyncio import AsyncSession

log = get_logger(__name__)

# * Number of counter rows merged per batch during a chat migration. The
# * merge runs one delete plus one upsert per counter, so an
# * unbounded batch would create an unbounded number of pending round
# * trips on a legacy group that holds a counter per warned user.
_MIGRATION_CHUNK_SIZE: int = 200

# ──────────────────────────── Tables ────────────────────────────── #
# * The surrogate primary key stays out of the returned documents: the
# * helpers expose the federation fields, not the storage identity.
_WARN_COLUMNS = [c for c in warns.c if c.name != "id"]


def _scope_filter(
    table: Table, user_id: int, chat_ids: Sequence[int] | None
) -> ColumnElement[bool]:
    """Match one user's rows, optionally limited to a set of chats.

    ``chat_ids=None`` covers every chat the user appears in.
    """
    if chat_ids is None:
        return table.c.user_id == user_id
    return and_(table.c.user_id == user_id, table.c.chat_id.in_(chat_ids))


# ───────────────────────────── Counters ──────────────────────────── #


async def _sync_warn_count(user_id: int, chat_id: int) -> int:
    """Read the counter row, or backfill it from warn history when missing.

    The backfill uses an insert-only conflict clause, so concurrent
    callers cannot double-backfill the same missing counter row: the
    loser of the insert race updates nothing and re-reads the winner's
    count instead.
    """
    row = await db_call(
        lambda: fetch_one(
            select(warn_counts.c.count).where(
                warn_counts.c.user_id == user_id,
                warn_counts.c.chat_id == chat_id,
            )
        )
    )
    if row is not None:
        counter: WarnCountDoc = cast("WarnCountDoc", row)
        return int(counter.get("count") or 0)

    total = await db_call(
        lambda: fetch_value(
            select(func.count())
            .select_from(warns)
            .where(warns.c.user_id == user_id, warns.c.chat_id == chat_id)
        )
    )
    count = int(total or 0)
    if count > 0:
        rows = await db_call(
            lambda: run_returning(
                pg_insert(warn_counts)
                .values(
                    user_id=user_id,
                    chat_id=chat_id,
                    count=count,
                    updated_at=utc_now(),
                )
                # * Insert-only conflict clause: an existing counter keeps
                # * its own count, exactly like the former ``$setOnInsert``.
                .on_conflict_do_nothing(index_elements=["user_id", "chat_id"])
                .returning(warn_counts.c.count)
            )
        )
        if rows:
            return int(rows[0]["count"] or 0)
        # * A concurrent caller won the backfill insert; the row exists
        # * now, so re-read the winner's count instead of failing.
        row = await db_call(
            lambda: fetch_one(
                select(warn_counts.c.count).where(
                    warn_counts.c.user_id == user_id,
                    warn_counts.c.chat_id == chat_id,
                )
            )
        )
        if row is not None:
            return int(row["count"] or 0)
    return count


async def _recount_and_store(user_id: int, chat_id: int) -> None:
    """Rebuild the counter from warn history after a failed atomic update.

    Single owner for the repair path shared by every counter-write failure
    below, so a fix to the recount logic cannot drift between call sites.

    The recount and the write share one transaction, and the transaction
    holds the counter row before it counts the history. A recount that
    read the history in one statement and wrote the absolute count in
    another could overwrite the increment of a warning that landed in
    between: the counter would then sit one below the history, and the
    auto-ban threshold would fire one warning late. Locking the counter
    row first makes the concurrent ``add_warn`` wait, so it applies its
    increment to the recounted value instead of losing it.
    """
    now = utc_now()

    async def _work(sess: AsyncSession) -> None:
        # * The conflict clause locks the counter row for the rest of the
        # * transaction, and the insert takes the primary-key lock when the
        # * row is missing. Either way a concurrent add_warn waits here.
        await sess.execute(
            pg_insert(warn_counts)
            .values(user_id=user_id, chat_id=chat_id, count=0, updated_at=now)
            .on_conflict_do_update(
                index_elements=["user_id", "chat_id"],
                set_={"updated_at": now},
            )
        )
        total = (
            await sess.execute(
                select(func.count())
                .select_from(warns)
                .where(warns.c.user_id == user_id, warns.c.chat_id == chat_id)
            )
        ).scalar()
        count = int(total or 0)
        if count <= 0:
            await sess.execute(
                warn_counts.delete().where(
                    warn_counts.c.user_id == user_id,
                    warn_counts.c.chat_id == chat_id,
                )
            )
            return
        await sess.execute(
            update(warn_counts)
            .where(
                warn_counts.c.user_id == user_id,
                warn_counts.c.chat_id == chat_id,
            )
            .values(count=count, updated_at=now)
        )

    await run_transaction(_work)


async def _repair_counter_delete(
    user_id: int,
    chat_ids: Sequence[int] | None,
    *,
    counts_many: bool,
    scope: str,
) -> None:
    """Best-effort repair after a counter-delete failure in _clear_warn_docs.

    A surviving counter keeps stale counts that later warns increment
    from, so the clear must not end with only a log line. Single-pair
    clears recount the pair (history is already gone, so the recount
    lands at zero and drops the stale row); multi-pair clears retry the
    delete. The delete retry runs a bounded number of attempts with a
    short backoff; a persistent outage stays error-logged but non-fatal
    like the original delete failure so a clear never reports failure
    for a repair problem. Cancellation propagates.
    """
    if counts_many:
        for attempt in range(3):
            try:
                await db_call(
                    lambda: run(
                        warn_counts.delete().where(
                            _scope_filter(warn_counts, user_id, chat_ids)
                        )
                    ),
                    timeout=None,
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
    if not chat_ids:
        return
    try:
        await _recount_and_store(user_id, int(chat_ids[0]))
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("%s counter repair failed", scope)


async def warn_count(user_id: int, chat_id: int) -> int:
    """Get the current number of warnings for a user in a specific chat."""
    return await _sync_warn_count(user_id, chat_id)


# ────────────────────────────── Records ──────────────────────────── #


async def add_warn(user_id: int, reason: str, admin_id: int, chat_id: int) -> int:
    """Add a new warning to a user in a specific chat.

    The history row and the counter land in one transaction. They must
    agree: the counter is what the auto-ban threshold reads, so a
    history row without its counter (or the other way round) would
    silently delay the ban that the warning earned. A crash between two
    separate statements cannot be repaired afterwards, so the two
    writes share a transaction instead.
    """
    now = utc_now()

    async def _work(sess: AsyncSession) -> int:
        await sess.execute(
            pg_insert(warns).values(
                user_id=user_id,
                chat_id=chat_id,
                reason=reason,
                admin_id=admin_id,
                timestamp=now,
            )
        )
        result = await sess.execute(
            pg_insert(warn_counts)
            .values(user_id=user_id, chat_id=chat_id, count=1, updated_at=now)
            .on_conflict_do_update(
                index_elements=["user_id", "chat_id"],
                set_={"count": warn_counts.c.count + 1, "updated_at": now},
            )
            .returning(warn_counts.c.count)
        )
        stored = result.scalar()
        if stored is None:
            # * The server returned no counter row, so the count is
            # * unknown. The transaction is rolled back rather than
            # * committing a warning whose count is missing.
            raise RuntimeError(
                f"warn counter for user {user_id} in chat {chat_id} returned no row"
            )
        return int(stored)

    return await run_transaction(_work)


async def clear_warns(user_id: int, chat_id: int) -> int:
    """Remove ALL warnings for a user in a specific chat.

    Raises the warns-delete failure instead of returning 0: a 0 return
    means "nothing to clear", and reporting an outage as an empty state
    would mislead the moderator. Counter-delete failures stay
    error-logged but non-fatal (the stale counter is flagged for repair
    while the requested clear itself succeeded).
    """
    return await _clear_warn_docs(
        user_id,
        [chat_id],
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
    return await _clear_warn_docs(
        user_id,
        None,
        counts_many=True,
        scope=f"clear_all_warns user={user_id}",
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
    return await _clear_warn_docs(
        user_id,
        chats,
        counts_many=True,
        scope=f"clear_warns_for_chats user={user_id} chats={len(chats)}",
    )


async def _clear_warn_docs(
    user_id: int,
    chat_ids: Sequence[int] | None,
    *,
    counts_many: bool,
    scope: str,
) -> int:
    """Delete warn history plus counter rows; shared by every clear path.

    Returns the history deleted count. Raises the history-delete failure
    (a 0 return means "nothing to clear"); counter-delete failures are
    error-logged for operator repair while the clear itself succeeded.
    Cancellation propagates instead of reporting success.
    """
    # * The two deletes write to different tables and neither reads the
    # * other, so they run concurrently instead of costing four round
    # * trips on a federation-wide clear.
    warn_del, cnt_del = await asyncio.gather(
        db_call(
            lambda: run(warns.delete().where(_scope_filter(warns, user_id, chat_ids))),
            timeout=None,
        ),
        db_call(
            lambda: run(
                warn_counts.delete().where(
                    _scope_filter(warn_counts, user_id, chat_ids)
                )
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
            user_id, chat_ids, counts_many=counts_many, scope=scope
        )
    if isinstance(warn_del, BaseException):
        log.error("%s warns delete failed: %s", scope, warn_del)
        raise warn_del
    return int(warn_del)


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
    order = (
        (warns.c.timestamp.desc(), warns.c.id.desc())
        if newest_first
        else (warns.c.timestamp.asc(), warns.c.id.asc())
    )
    stmt = (
        select(*_WARN_COLUMNS)
        .where(warns.c.user_id == user_id, warns.c.chat_id == chat_id)
        # * The surrogate id breaks timestamp ties so a page boundary
        # * cannot repeat or skip a record.
        .order_by(*order)
        .offset(max(0, skip))
    )
    if limit is not None:
        stmt = stmt.limit(max(1, limit))
    rows = await db_call(lambda: fetch_all(stmt))
    return cast("list[WarnDoc]", rows)


async def remove_last_warn(user_id: int, chat_id: int) -> bool:
    """Delete the most recent warn document. Returns True if one was removed."""
    row = await db_call(
        lambda: fetch_one(
            select(warns.c.id)
            .where(warns.c.user_id == user_id, warns.c.chat_id == chat_id)
            .order_by(warns.c.timestamp.desc(), warns.c.id.desc())
            .limit(1)
        )
    )
    if row is None:
        return False
    warn_id = int(row["id"])

    # * The delete and the counter decrement write to different tables and
    # * neither reads the other, so they run concurrently.
    del_res, counter = await asyncio.gather(
        db_call(lambda: run(warns.delete().where(warns.c.id == warn_id))),
        db_call(
            lambda: run_returning(
                warn_counts.update()
                .where(
                    warn_counts.c.user_id == user_id,
                    warn_counts.c.chat_id == chat_id,
                    warn_counts.c.count > 0,
                )
                .values(count=warn_counts.c.count - 1, updated_at=utc_now())
                .returning(warn_counts.c.count)
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
    if del_res == 0:
        await _recount_and_store(user_id, chat_id)
        return False

    if isinstance(counter, asyncio.CancelledError):
        raise counter
    if isinstance(counter, BaseException) or not counter:
        await _recount_and_store(user_id, chat_id)
    return True


async def user_total_warns(user_id: int) -> int:
    """Total number of warning rows recorded against the user (all groups)."""
    total = await db_call(
        lambda: fetch_value(
            select(func.count()).select_from(warns).where(warns.c.user_id == user_id)
        )
    )
    return int(total or 0)


async def user_warn_groups(user_id: int) -> list[tuple[int, int]]:
    """Return [(chat_id, count), ...] for every group where the user has warns, newest first."""
    rows = await db_call(
        lambda: fetch_all(
            select(warn_counts.c.chat_id, warn_counts.c.count)
            .where(warn_counts.c.user_id == user_id, warn_counts.c.count > 0)
            .order_by(warn_counts.c.updated_at.desc())
        )
    )
    return [(int(d["chat_id"]), int(d["count"])) for d in rows]


# ───────────────────────────── Migration ─────────────────────────── #


async def migrate_records(old_chat_id: int, new_chat_id: int) -> bool:
    """Repoint every warn record and counter from ``old_chat_id`` to ``new_chat_id``.

    Called when a basic group migrates to a supergroup. Both ``warns`` (audit
    history) and ``warn_counts`` (the per-group counter rows that gate
    the threshold ban) are keyed by ``chat_id``, so without this the
    supergroup would silently start with a clean slate and lose all warning
    history from the legacy chat. Counter rows merge by summation: when the
    supergroup already holds warns, the counts add up instead of a blind
    overwrite losing one side or violating the per-pair primary key.
    Each old counter is consumed with an atomic take (removed before its
    count is added to the new pair), so a crash plus retry can only
    under-count, never double-count into a false threshold ban. Returns ``True``
    if any record was updated.
    """
    try:
        history_affected = await db_call(
            lambda: run(
                warns.update()
                .where(warns.c.chat_id == old_chat_id)
                .values(chat_id=new_chat_id)
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
    matched_any = history_affected > 0

    try:
        old_counters = await db_call(
            lambda: fetch_all(
                select(warn_counts.c.user_id, warn_counts.c.count).where(
                    warn_counts.c.chat_id == old_chat_id
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

    async def _merge_one_counter(doc: dict[str, Any]) -> bool:
        """Atomic-take one old counter and land its count on the new pair.

        Returns True when this user contributed to the migration. The take
        and the landing share one transaction: with two statements the
        delete could commit and the upsert then fail, and the count would
        be gone with no row left to retry from. The old row is therefore
        removed in the same transaction that adds its count to the new
        pair, so a crash leaves both sides untouched.

        Per-user failures log and return False; cancellation propagates
        via gather_bounded below.
        """
        uid = doc.get("user_id")
        cnt = int(doc.get("count", 0))
        if uid is None or cnt <= 0:
            return False
        now = utc_now()

        async def _work(sess: AsyncSession) -> bool:
            taken_result = await sess.execute(
                warn_counts.delete().where(
                    warn_counts.c.user_id == uid,
                    warn_counts.c.chat_id == old_chat_id,
                )
            )
            # * A write returns a cursor result, which carries the affected
            # * row count. The generic result type does not expose it.
            if cast("CursorResult", taken_result).rowcount == 0:
                return False
            await sess.execute(
                pg_insert(warn_counts)
                .values(
                    user_id=uid,
                    chat_id=new_chat_id,
                    count=cnt,
                    updated_at=now,
                )
                .on_conflict_do_update(
                    index_elements=["user_id", "chat_id"],
                    set_={"count": warn_counts.c.count + cnt, "updated_at": now},
                )
            )
            return True

        try:
            return await run_transaction(_work)
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
    # * The counter list is chunked: a legacy group can hold a counter per
    # * warned user, and creating one task per counter up front would
    # * build an unbounded task list and an unbounded number of pending
    # * round trips.
    merged = False
    failed: list[dict[str, Any]] = []
    for chunk in batched(old_counters, _MIGRATION_CHUNK_SIZE, strict=False):
        results = await gather_bounded([_merge_one_counter(doc) for doc in chunk])
        merged = merged or any(r is True for r in results)
        failed.extend(
            doc for doc, ok in zip(chunk, results, strict=False) if ok is not True
        )
    # * One bounded retry for the counters whose transaction failed: the
    # * old row is still there, so the retry can still move its count.
    if failed:
        retry = await gather_bounded([_merge_one_counter(doc) for doc in failed])
        merged = merged or any(r is True for r in retry)
        still_failed = sum(1 for r in retry if r is not True)
        if still_failed:
            # * The stale rows are dropped below, so their counts are lost.
            # * Under-counting is the safe direction: a lost count delays
            # * the auto-ban, a double count would cause a wrongful one.
            log.error(
                "warns_db.migrate_records (%d -> %d): %d counters could not "
                "be merged and their counts are dropped",
                old_chat_id,
                new_chat_id,
                still_failed,
            )
    matched_any = matched_any or merged
    try:
        await db_call(
            lambda: run(
                warn_counts.delete().where(warn_counts.c.chat_id == old_chat_id)
            ),
            timeout=None,
        )
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

    Sums ``count`` across all ``warn_counts`` rows for the user via a
    server-side aggregate, avoiding a Python-side sum over a
    potentially large result set.  Returns 0 when the user has no active
    warnings.
    """
    # * The aggregate scans every warn counter of the user; it is bounded by
    # * the user's own rows and stays inside the default call budget.
    total = await db_call(
        lambda: fetch_value(
            select(func.sum(warn_counts.c.count)).where(
                warn_counts.c.user_id == user_id,
                warn_counts.c.count > 0,
            )
        )
    )
    return int(total or 0)
