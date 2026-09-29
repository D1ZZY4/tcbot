# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Ban queries: active lookups, pages, counts, and per-user history."""

from __future__ import annotations

from tcbot.database.documents import BanDoc
from tcbot.database.mongos import db_call

from .records import _bans


async def get_active_ban(user_id: int) -> BanDoc | None:
    """Get the currently active ban for a specific user."""
    return await db_call(
        _bans().find_one(
            {"banned_user_id": user_id, "is_active": True},
            sort=[("timestamp", -1), ("ban_id", -1)],
        )
    )


async def get_ban(ban_id: str) -> BanDoc | None:
    """Get any ban record by its unique ban_id."""
    return await db_call(_bans().find_one({"ban_id": ban_id}))


async def active_ban_count() -> int:
    """Count the total number of currently active bans."""
    return await db_call(_bans().count_documents({"is_active": True}))


async def active_bans_page(skip: int, limit: int) -> list[BanDoc]:
    """Return one page of active bans, newest first (server-side skip/limit).

    Only the visible slice travels over the wire regardless of federation
    size. Uses the ``(is_active, timestamp, ban_id)`` index.
    """
    # * Clamp once so cursor limit and fetch length can never disagree;
    # * callers always pass positive values, this only pins the edge.
    page_size = max(1, limit)
    return await db_call(
        _bans()
        .find(
            {"is_active": True},
            {"_id": 0},
            sort=[("timestamp", -1), ("ban_id", -1)],
        )
        .skip(max(0, skip))
        .limit(page_size)
        .to_list(length=page_size)
    )


async def active_bans_for_users(user_ids: list[int]) -> list[BanDoc]:
    """Return active bans for the given users (server-side ``$in``).

    Backs name-search results without loading the whole active-ban list.
    Uses the ``(banned_user_id, is_active, ...)`` index.
    """
    if not user_ids:
        return []
    return await db_call(
        _bans()
        .find(
            {"banned_user_id": {"$in": user_ids}, "is_active": True},
            {"_id": 0},
            sort=[("timestamp", -1), ("ban_id", -1)],
        )
        .to_list(None)
    )


async def user_appealable_bans(
    user_id: int, *, skip: int = 0, limit: int | None = None
) -> list[BanDoc]:
    """Return the user's bans that ever had an appeal submitted, newest first.

    Server-side version of the ``appeal_log_msg_id is not None`` filter;
    same predicate as :func:`user_appeal_count`, served by the sparse
    ``(banned_user_id, appeal_log_msg_id)`` index. ``limit=None`` returns
    the full list (backwards compatible).
    """
    cursor = (
        _bans()
        .find(
            {
                "banned_user_id": user_id,
                "appeal_log_msg_id": {"$ne": None, "$exists": True},
            },
            {"_id": 0},
            sort=[("timestamp", -1), ("ban_id", -1)],
        )
        .skip(max(0, skip))
    )
    if limit is not None:
        cursor = cursor.limit(max(1, limit))
    return await db_call(cursor.to_list(limit))


async def active_ban_user_ids() -> list[int]:
    """Return only the user IDs of all active bans (projection-only, fastest path).

    Uses ``distinct`` so the full ban documents never travel, and duplicate
    active rows for one user collapse to a single ID for the fan-out.
    """
    return await db_call(_bans().distinct("banned_user_id", {"is_active": True}))


async def user_bans(
    user_id: int, *, skip: int = 0, limit: int | None = None
) -> list[BanDoc]:
    """Return every ban (active + inactive) for a user, newest first.

    ``limit=None`` returns the full list (backwards compatible).
    """
    cursor = (
        _bans()
        .find(
            {"banned_user_id": user_id},
            {"_id": 0},
            sort=[("timestamp", -1), ("ban_id", -1)],
        )
        .skip(max(0, skip))
    )
    if limit is not None:
        cursor = cursor.limit(max(1, limit))
    return await db_call(cursor.to_list(limit))


async def user_ban_count(user_id: int) -> int:
    """Count every ban ever issued against the user."""
    return await db_call(_bans().count_documents({"banned_user_id": user_id}))


async def user_appeal_count(user_id: int) -> int:
    """Count bans on this user that ever had an appeal submitted."""
    return await db_call(
        _bans().count_documents(
            {
                "banned_user_id": user_id,
                "appeal_log_msg_id": {"$ne": None, "$exists": True},
            }
        )
    )
