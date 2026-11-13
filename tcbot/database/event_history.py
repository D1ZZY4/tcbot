# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Shared shape of the per-user moderation event histories.

The kick and the mute history are the same table shape over two
tables: a per-user event log ordered newest first, a per-user count, and
a chat migration that repoints the rows. This module owns that shape so
the two domains cannot drift apart in their ordering or their paging.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select

from tcbot.database.engine import db_call, fetch_all, fetch_value, run
from tcbot.utils.logger import get_logger

if TYPE_CHECKING:
    from sqlalchemy import Table

log = get_logger(__name__)


async def user_history(
    table: Table,
    user_id: int,
    *,
    skip: int = 0,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Return the events of one user, newest first.

    ``limit=None`` returns the full list.
    """
    columns = [c for c in table.c if c.name != "id"]
    stmt = (
        select(*columns)
        .where(table.c.user_id == user_id)
        # * Tie-break on the surrogate id so the order is stable when two
        # * events share a timestamp, matching the warn history.
        .order_by(table.c.timestamp.desc(), table.c.id.desc())
        .offset(max(0, skip))
    )
    if limit is not None:
        stmt = stmt.limit(max(1, limit))
    return await db_call(lambda: fetch_all(stmt))


async def user_event_count(table: Table, user_id: int) -> int:
    """Count every event ever logged against the user."""
    total = await db_call(
        lambda: fetch_value(
            select(func.count()).select_from(table).where(table.c.user_id == user_id)
        )
    )
    return int(total or 0)


async def migrate_chat(
    table: Table, old_chat_id: int, new_chat_id: int, *, label: str
) -> bool:
    """Repoint every event of ``table`` from ``old_chat_id`` to ``new_chat_id``.

    Called on basic-group to supergroup migration so the history does
    not split across the legacy chat. These rows carry no unique
    per-pair state, so a plain repoint is safe. Cancellation propagates.
    """
    try:
        affected = await db_call(
            lambda: run(
                table.update()
                .where(table.c.chat_id == old_chat_id)
                .values(chat_id=new_chat_id)
            )
        )
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception(
            "%s.migrate_records (%d -> %d) failed", label, old_chat_id, new_chat_id
        )
        return False
    return affected > 0
