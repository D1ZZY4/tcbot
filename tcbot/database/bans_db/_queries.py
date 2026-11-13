# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Read helpers over the community ban decisions."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select

from tcbot.database.base import moderation_actions, moderation_appeals
from tcbot.database.documents import BanDoc
from tcbot.database.engine import db_call, fetch_all, fetch_count, fetch_one
from tcbot.utils.time_and_date import utc_now

from ._compose import compose_rows
from ._shared import ACTION_COLUMNS


async def action_by_ref(ban_id: str) -> dict[str, Any] | None:
    """Return the decision row of one public reference."""
    return await db_call(
        lambda: fetch_one(
            select(*ACTION_COLUMNS).where(
                moderation_actions.c.external_ref == ban_id,
                moderation_actions.c.action_type == "ban",
            )
        )
    )


async def get_active_ban(user_id: int) -> BanDoc | None:
    """Get the currently active ban for a specific user."""
    rows = await db_call(
        lambda: fetch_all(
            select(*ACTION_COLUMNS)
            .where(
                moderation_actions.c.target_user_id == user_id,
                moderation_actions.c.action_type == "ban",
                moderation_actions.c.status == "active",
                (moderation_actions.c.expires_at.is_(None))
                | (moderation_actions.c.expires_at > utc_now()),
            )
            .order_by(moderation_actions.c.created_at.desc())
            .limit(1)
        )
    )
    docs = await compose_rows(rows)
    return docs[0] if docs else None


async def get_ban(ban_id: str) -> BanDoc | None:
    """Get any ban record by its public reference."""
    rows = await db_call(
        lambda: fetch_all(
            select(*ACTION_COLUMNS).where(
                moderation_actions.c.external_ref == ban_id,
                moderation_actions.c.action_type == "ban",
            )
        )
    )
    docs = await compose_rows(rows)
    return docs[0] if docs else None


async def active_ban_count() -> int:
    """Count the total number of currently active bans."""
    return await db_call(
        lambda: fetch_count(
            select(func.count())
            .select_from(moderation_actions)
            .where(
                moderation_actions.c.action_type == "ban",
                moderation_actions.c.status == "active",
            )
        )
    )


async def active_bans_page(skip: int, limit: int) -> list[BanDoc]:
    """Return one page of active bans, newest first (server-side skip/limit).

    Only the visible slice travels over the wire regardless of community
    size.
    """
    # * Clamp once so cursor limit and fetch length can never disagree;
    # * callers always pass positive values, this only pins the edge.
    page_size = max(1, limit)
    rows = await db_call(
        lambda: fetch_all(
            select(*ACTION_COLUMNS)
            .where(
                moderation_actions.c.action_type == "ban",
                moderation_actions.c.status == "active",
            )
            .order_by(moderation_actions.c.created_at.desc())
            .offset(max(0, skip))
            .limit(page_size)
        )
    )
    return await compose_rows(rows)


async def active_bans_for_users(user_ids: list[int]) -> list[BanDoc]:
    """Return active bans for the given users (server-side ``IN``).

    Backs name-search results without loading the whole active-ban list.
    """
    if not user_ids:
        return []
    rows = await db_call(
        lambda: fetch_all(
            select(*ACTION_COLUMNS)
            .where(
                moderation_actions.c.target_user_id.in_(user_ids),
                moderation_actions.c.action_type == "ban",
                moderation_actions.c.status == "active",
            )
            .order_by(moderation_actions.c.created_at.desc())
        )
    )
    return await compose_rows(rows)


async def user_appealable_bans(
    user_id: int, *, skip: int = 0, limit: int | None = None
) -> list[BanDoc]:
    """Return the user's bans that ever had an appeal submitted, newest first.

    Server-side version of the "appeal was submitted" filter.
    ``limit=None`` returns the full list.
    """
    stmt = (
        select(*ACTION_COLUMNS)
        .where(
            moderation_actions.c.target_user_id == user_id,
            moderation_actions.c.action_type == "ban",
            moderation_actions.c.id.in_(
                select(moderation_appeals.c.action_id).where(
                    moderation_appeals.c.status.isnot(None)
                )
            ),
        )
        .order_by(moderation_actions.c.created_at.desc())
        .offset(max(0, skip))
    )
    if limit is not None:
        stmt = stmt.limit(max(1, limit))
    rows = await db_call(lambda: fetch_all(stmt))
    return await compose_rows(rows)


async def active_ban_user_ids() -> list[int]:
    """Return only the user IDs of all active bans (projection-only, fastest path).

    Uses ``DISTINCT`` so the full ban documents never travel, and duplicate
    active rows for one user collapse to a single ID for the fan-out.
    """
    rows = await db_call(
        lambda: fetch_all(
            select(moderation_actions.c.target_user_id)
            .where(
                moderation_actions.c.action_type == "ban",
                moderation_actions.c.status == "active",
            )
            .distinct()
        )
    )
    return [int(row["target_user_id"]) for row in rows]


async def user_bans(
    user_id: int, *, skip: int = 0, limit: int | None = None
) -> list[BanDoc]:
    """Return every ban (active + inactive) for a user, newest first.

    ``limit=None`` returns the full list (backwards compatible).
    """
    stmt = (
        select(*ACTION_COLUMNS)
        .where(
            moderation_actions.c.target_user_id == user_id,
            moderation_actions.c.action_type == "ban",
        )
        .order_by(moderation_actions.c.created_at.desc())
        .offset(max(0, skip))
    )
    if limit is not None:
        stmt = stmt.limit(max(1, limit))
    rows = await db_call(lambda: fetch_all(stmt))
    return await compose_rows(rows)


async def user_ban_count(user_id: int) -> int:
    """Count every ban ever issued against the user."""
    return await db_call(
        lambda: fetch_count(
            select(func.count())
            .select_from(moderation_actions)
            .where(
                moderation_actions.c.target_user_id == user_id,
                moderation_actions.c.action_type == "ban",
            )
        )
    )


async def user_appeal_count(user_id: int) -> int:
    """Count bans on this user that ever had an appeal submitted."""
    return await db_call(
        lambda: fetch_count(
            select(func.count())
            .select_from(moderation_appeals)
            .where(
                moderation_appeals.c.appellant_user_id == user_id,
                moderation_appeals.c.status.isnot(None),
            )
        )
    )
