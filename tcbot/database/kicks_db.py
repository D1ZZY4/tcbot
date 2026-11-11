# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Kick log helpers - tracks all kick events in groups."""

from __future__ import annotations

import asyncio
from typing import cast

from sqlalchemy import func, select

from tcbot.database.base import kicks
from tcbot.database.documents import KickDoc
from tcbot.database.engine import db_call, fetch_all, fetch_value, run
from tcbot.database.types import ChatId, UserId
from tcbot.utils.logger import get_logger
from tcbot.utils.time_and_date import utc_now

log = get_logger(__name__)

# ──────────────────────────── Table ─────────────────────────────── #
# * The surrogate primary key stays out of the returned documents: the
# * helpers expose the federation fields, not the storage identity.
_KICK_COLUMNS = [c for c in kicks.c if c.name != "id"]

# ─────────────────────── Collection Helpers ─────────────────────── #
# * Internal table access utilities for the kicks database


# ──────────────────────────── Mutations ─────────────────────────── #
# * Functions that create or modify kick log records
# * Used exclusively for audit logging of moderation actions


async def log_kick(user_id: int, chat_id: int, reason: str, admin_id: int) -> None:
    """Log a kick event to the database for audit purposes."""
    doc: KickDoc = {
        "user_id": UserId(user_id),
        "chat_id": ChatId(chat_id),
        "reason": reason,
        "admin_id": UserId(admin_id),
        "timestamp": utc_now(),
    }
    await db_call(
        lambda: run(
            kicks.insert().values(
                user_id=doc["user_id"],
                chat_id=doc["chat_id"],
                reason=doc["reason"],
                admin_id=doc["admin_id"],
                timestamp=doc["timestamp"],
            )
        )
    )


# ─────────────────────── Per-user history ───────────────────────── #


async def user_kicks(
    user_id: int, *, skip: int = 0, limit: int | None = None
) -> list[KickDoc]:
    """Return every kick record for a user, newest first.

    ``limit=None`` returns the full list (backwards compatible).
    """
    stmt = (
        select(*_KICK_COLUMNS)
        .where(kicks.c.user_id == user_id)
        # * Tie-break on the surrogate id so the order is stable when two
        # * events share a timestamp, matching the warn history.
        .order_by(kicks.c.timestamp.desc(), kicks.c.id.desc())
        .offset(max(0, skip))
    )
    if limit is not None:
        stmt = stmt.limit(max(1, limit))
    rows = await db_call(lambda: fetch_all(stmt))
    return cast("list[KickDoc]", rows)


async def user_kick_count(user_id: int) -> int:
    """Count every kick ever logged against the user."""
    total = await db_call(
        lambda: fetch_value(
            select(func.count()).select_from(kicks).where(kicks.c.user_id == user_id)
        )
    )
    return int(total or 0)


async def migrate_records(old_chat_id: int, new_chat_id: int) -> bool:
    """Repoint every kick record from ``old_chat_id`` to ``new_chat_id``.

    Called on basic-group to supergroup migration so /check kick history
    does not split across the legacy chat. Kick rows carry no unique
    per-pair state, so a plain repoint is safe. Cancellation propagates.
    """
    try:
        affected = await db_call(
            lambda: run(
                kicks.update()
                .where(kicks.c.chat_id == old_chat_id)
                .values(chat_id=new_chat_id)
            )
        )
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception(
            "kicks_db.migrate_records (%d -> %d) failed", old_chat_id, new_chat_id
        )
        return False
    return affected > 0
