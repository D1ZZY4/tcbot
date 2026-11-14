# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Group kick helpers over the moderation decision tables.

A kick is one decision in ``moderation_actions``. It is bound to the
group it happened in, so it never reaches the other managed groups.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from tcbot.database import moderation_db
from tcbot.database.base import moderation_actions
from tcbot.database.documents import KickDoc
from tcbot.database.engine import db_call, fetch_all, fetch_value, run_transaction
from tcbot.database.types import ChatId, UserId
from tcbot.utils.logger import get_logger
from tcbot.utils.time_and_date import utc_now

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy.ext.asyncio import AsyncSession

log = get_logger(__name__)

# ──────────────────────────── Table ─────────────────────────────── #
# * The surrogate primary key stays out of the returned documents: the
# * helpers expose the community fields, not the storage identity.
_KICK_COLUMNS = (
    moderation_actions.c.id,
    moderation_actions.c.target_user_id,
    moderation_actions.c.actor_user_id,
    moderation_actions.c.reason,
    moderation_actions.c.chat_id,
    moderation_actions.c.created_at,
    moderation_actions.c.status,
    moderation_actions.c.case_id,
)

# ──────────────────────────── Mutations ─────────────────────────── #
# * Functions that create or modify kick decisions.
# * Used exclusively for audit logging of moderation actions


async def log_kick(user_id: int, chat_id: int, reason: str, admin_id: int) -> None:
    """Log a kick event to the database for audit purposes."""
    now = utc_now()

    async def _work(sess: AsyncSession) -> None:
        case_id = await _open_case(sess, user_id, admin_id, reason, chat_id)
        await sess.execute(
            pg_insert(moderation_actions).values(
                action_type="kick",
                scope_type="chat",
                chat_id=chat_id,
                origin_chat_id=chat_id,
                target_user_id=user_id,
                actor_user_id=admin_id,
                reason=reason,
                created_at=now,
                status="completed",
                case_id=case_id,
                action_origin="manual",
            )
        )
        # * The investigation ends with its decision: an open case is
        # * picked up by the next decision about the same user, so the
        # * history would collapse into one case per user.
        await moderation_db.close_case(sess, case_id, admin_id)

    await run_transaction(_work)


async def _open_case(
    sess: AsyncSession, target_id: int, admin_id: int, reason: str, chat_id: int
) -> int:
    """Return the open case of the target, or open one for the decision."""
    return await moderation_db.open_case(
        sess,
        target_id,
        admin_id,
        title=f"Kick of {target_id} in group {chat_id}",
        summary=reason,
        severity="medium",
        requires_evidence=False,
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
        .where(
            moderation_actions.c.target_user_id == user_id,
            moderation_actions.c.action_type == "kick",
        )
        .order_by(moderation_actions.c.created_at.desc())
        .offset(max(0, skip))
    )
    if limit is not None:
        stmt = stmt.limit(max(1, limit))
    rows = await db_call(lambda: fetch_all(stmt))
    return [
        KickDoc(
            target_user_id=UserId(int(row["target_user_id"])),
            chat_id=ChatId(int(row["chat_id"])),
            reason=str(row["reason"]),
            actor_user_id=UserId(int(row["actor_user_id"])),
            timestamp=cast("datetime", row["created_at"]),
        )
        for row in rows
    ]


async def user_kick_count(user_id: int) -> int:
    """Count every kick ever logged against the user."""
    total = await db_call(
        lambda: fetch_value(
            select(func.count())
            .select_from(moderation_actions)
            .where(
                moderation_actions.c.target_user_id == user_id,
                moderation_actions.c.action_type == "kick",
            )
        )
    )
    return int(total or 0)


# ───────────────────────────── Migration ─────────────────────────── #
# * The community schema moves a group as one transaction, so the
# * decisions of a group follow it through
# * :func:`tcbot.database.groups_db.migrate_group`.
