# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Mute log helpers - tracks all mute events in groups."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, cast

from sqlalchemy import case, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from tcbot.database.base import active_mutes, mutes
from tcbot.database.documents import ActiveMuteDoc, MuteDoc
from tcbot.database.engine import db_call, fetch_all, fetch_one, fetch_value, run
from tcbot.database.types import ChatId, UserId
from tcbot.utils.logger import get_logger
from tcbot.utils.time_and_date import utc_now

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy import ColumnElement

log = get_logger(__name__)

# ──────────────────────────── Tables ────────────────────────────── #
# * The surrogate primary key stays out of the returned documents: the
# * helpers expose the federation fields, not the storage identity.
_MUTE_COLUMNS = [c for c in mutes.c if c.name != "id"]

# * The live mute row is keyed by the muted user, so the whole row is
# * the document: there is no surrogate id to hide.
_ACTIVE_MUTE_COLUMNS = list(active_mutes.c)

# ─────────────────────── Table helpers ────────────────────────── #
# * Internal table access utilities for the mutes database


def _not_expired_clause(now: datetime) -> ColumnElement[bool]:
    """Match permanent (``NULL`` ``until_date``) or still-valid timed mutes.

    Single owner for the expiry predicate so the query-time filter cannot
    drift from the permanent-mute semantics (permanent rows never expire).
    """
    return or_(
        active_mutes.c.until_date.is_(None),
        active_mutes.c.until_date > now,
    )


# ──────────────────────────── Mutations ─────────────────────────── #
# * Functions that create or modify mute log records
# * Primarily used for audit logging of moderation actions


async def log_mute(
    user_id: int,
    chat_id: int,
    reason: str,
    admin_id: int,
    *,
    duration_secs: int | None = None,
) -> None:
    """Log a mute event to the database for audit purposes.

    ``duration_secs`` is ``None`` for a permanent mute, or the total number of
    seconds for a timed mute. Storing it allows mute-history views to show
    how long a restriction was intended to last.
    """
    doc: MuteDoc = {
        "user_id": UserId(user_id),
        "chat_id": ChatId(chat_id),
        "reason": reason,
        "admin_id": UserId(admin_id),
        "timestamp": utc_now(),
    }
    if duration_secs is not None:
        doc["duration_secs"] = duration_secs
    await db_call(
        lambda: run(
            mutes.insert().values(
                user_id=doc["user_id"],
                chat_id=doc["chat_id"],
                reason=doc["reason"],
                admin_id=doc["admin_id"],
                timestamp=doc["timestamp"],
                duration_secs=doc.get("duration_secs"),
            )
        )
    )


# ──────────────────────── Active mute store ─────────────────────── #
# * One row per muted user in `active_mutes`.
# * set_active_mute is called by _execute_mute before the restrict fan-out
# * (fail-closed: no group is touched when the record cannot persist).
# * clear_active_mute is called by execute_unmute.
# * get_active_mute / active_mute_docs filter out expired timed mutes at
#   query time so no background cleanup job is needed.


async def set_active_mute(user_id: int, *, until: datetime | None = None) -> None:
    """Upsert the active mute entry for a user.

    Pass ``until=None`` for a permanent mute.  For timed mutes, pass the
    UTC datetime when the restriction expires (matches the ``until_date``
    value passed to ``restrict_chat_member``).

    The stored expiry only ever moves further into the future. A permanent
    mute is never downgraded to a timed one: overwriting a stored
    ``until_date`` of ``None`` with a deadline would let the row expire
    and the bot would lose the enforcement state for a user it still
    restricts. For the same reason a timed mute never shortens an expiry
    that already reaches further.
    """
    now = utc_now()
    if until is None:
        # * A permanent mute always wins: it outranks every deadline.
        await db_call(
            lambda: run(
                pg_insert(active_mutes)
                .values(user_id=UserId(user_id), until_date=None, timestamp=now)
                .on_conflict_do_update(
                    index_elements=["user_id"],
                    set_={"until_date": None, "timestamp": now},
                )
            )
        )
        return
    # * One atomic upsert: the statement reads the stored row and writes
    # * the new deadline in the same round trip, so two concurrent mutes
    # * cannot both miss the row and then collapse onto one insert. The
    # * conflict clause keeps a permanent mute permanent and otherwise
    # * keeps the later of the two deadlines.
    await db_call(
        lambda: run(
            pg_insert(active_mutes)
            .values(user_id=UserId(user_id), until_date=until, timestamp=now)
            .on_conflict_do_update(
                index_elements=["user_id"],
                set_={
                    "until_date": case(
                        (active_mutes.c.until_date.is_(None), None),
                        else_=func.greatest(active_mutes.c.until_date, until),
                    ),
                    "timestamp": now,
                },
            )
        )
    )


async def clear_active_mute(user_id: int) -> None:
    """Remove the active mute entry when a user is unmuted."""
    await db_call(
        lambda: run(
            active_mutes.delete().where(active_mutes.c.user_id == UserId(user_id))
        )
    )


async def get_active_mute(user_id: int) -> ActiveMuteDoc | None:
    """Return the active mute for a user, or None if none exists or has expired."""
    now = utc_now()
    row = await db_call(
        lambda: fetch_one(
            select(*_ACTIVE_MUTE_COLUMNS).where(
                active_mutes.c.user_id == UserId(user_id),
                _not_expired_clause(now),
            )
        )
    )
    return cast("ActiveMuteDoc | None", row)


async def active_mute_docs() -> list[ActiveMuteDoc]:
    """Return all currently active mute records (used for group-connect replay).

    Expired timed mutes (``until_date <= now``) are excluded at query time.
    """
    now = utc_now()
    rows = await db_call(
        lambda: fetch_all(select(*_ACTIVE_MUTE_COLUMNS).where(_not_expired_clause(now)))
    )
    return cast("list[ActiveMuteDoc]", rows)


# ─────────────────────── Per-user history ───────────────────────── #


async def user_mutes(
    user_id: int, *, skip: int = 0, limit: int | None = None
) -> list[MuteDoc]:
    """Return every mute record for a user, newest first.

    ``limit=None`` returns the full list (backwards compatible).
    """
    stmt = (
        select(*_MUTE_COLUMNS)
        .where(mutes.c.user_id == user_id)
        # * Tie-break on the surrogate id so the order is stable when two
        # * events share a timestamp, matching the warn history.
        .order_by(mutes.c.timestamp.desc(), mutes.c.id.desc())
        .offset(max(0, skip))
    )
    if limit is not None:
        stmt = stmt.limit(max(1, limit))
    rows = await db_call(lambda: fetch_all(stmt))
    return cast("list[MuteDoc]", rows)


async def user_mute_count(user_id: int) -> int:
    """Count every mute ever logged against the user."""
    total = await db_call(
        lambda: fetch_value(
            select(func.count()).select_from(mutes).where(mutes.c.user_id == user_id)
        )
    )
    return int(total or 0)


async def migrate_records(old_chat_id: int, new_chat_id: int) -> bool:
    """Repoint every mute record from ``old_chat_id`` to ``new_chat_id``.

    Called on basic-group to supergroup migration so /check mute history
    does not split across the legacy chat. Mute rows carry no unique
    per-pair state, so a plain repoint is safe. Cancellation propagates.
    """
    try:
        affected = await db_call(
            lambda: run(
                mutes.update()
                .where(mutes.c.chat_id == old_chat_id)
                .values(chat_id=new_chat_id)
            )
        )
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception(
            "mutes_db.migrate_records (%d -> %d) failed", old_chat_id, new_chat_id
        )
        return False
    return affected > 0
