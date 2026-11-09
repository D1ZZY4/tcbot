# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Connected-group queries, mutations, and the primary merge."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from tcbot.database.cache import (
    _ALL_GROUPS_KEY,
    active_groups_cache,
    connected_cache,
)
from tcbot.database.documents import GroupDoc
from tcbot.database.mongos import db_call
from tcbot.utils.time_and_date import utc_now

from .collections import _groups

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence
    from typing import Any


async def get_group_titles(chat_ids: list[int]) -> dict[int, str]:
    """Return {chat_id: title} for the given chat_ids; missing groups are absent."""
    if not chat_ids:
        return {}
    docs = await db_call(
        _groups()
        .find({"chat_id": {"$in": chat_ids}}, {"_id": 0, "chat_id": 1, "title": 1})
        .to_list(length=None)
    )
    return {int(d["chat_id"]): d.get("title") or str(d["chat_id"]) for d in docs}


async def refresh_group_title(chat_id: int, title: str) -> bool:
    """Update the stored title when live Telegram reports a different one.

    Returns True when a change was written (and the groups cache
    invalidated), False when already current or the group is unknown.
    Single atomic update: the ``$ne`` filter skips the write when the
    stored title already matches, so the common no-change path costs one
    round trip instead of two and a concurrent refresh cannot clobber a
    newer title with a stale read.
    """
    r = await db_call(
        _groups().update_one(
            {"chat_id": chat_id, "title": {"$ne": title}},
            {"$set": {"title": title}},
        )
    )
    if r.matched_count == 0:
        return False
    active_groups_cache.invalidate(_ALL_GROUPS_KEY)
    return True


async def is_connected(chat_id: int, *, fresh: bool = False) -> bool:
    """Check if a group is currently active and connected to the federation (L1->L2->DB cached).

    With ``fresh=True`` the cache is bypassed and the row is read directly
    from MongoDB, then the cache is refreshed. The origin guard uses
    ``fresh=True`` so a disconnect in another process is never hidden for
    up to the 120 s connection TTL; display reads keep the cached path.
    """

    async def _fetch() -> bool:
        return (
            await db_call(
                _groups().find_one({"chat_id": chat_id, "is_active": True}, {"_id": 1})
            )
            is not None
        )

    if fresh:
        connected = await _fetch()
        connected_cache.put(chat_id, connected)
        return connected
    return cast("bool", await connected_cache.get_or_fetch(chat_id, _fetch))


async def add_group(chat_id: int, title: str, added_by: int) -> None:
    """Add or update a group in the federated_groups collection."""
    await db_call(
        _groups().update_one(
            {"chat_id": chat_id},
            {
                "$set": {
                    "chat_id": chat_id,
                    "title": title,
                    "added_by": added_by,
                    "is_active": True,
                },
                # * First-connect date must survive re-adds and title
                # * refreshes: stats shows it as the join date, so keep it in
                # * $setOnInsert instead of rewriting history on every add.
                "$setOnInsert": {"added_date": utc_now()},
            },
            upsert=True,
        )
    )
    connected_cache.put(chat_id, True)  # noqa: FBT003
    active_groups_cache.invalidate(_ALL_GROUPS_KEY)


async def deactivate_group(chat_id: int) -> bool:
    """Mark a group as inactive (disconnect from federation)."""
    r = await db_call(
        _groups().update_one({"chat_id": chat_id}, {"$set": {"is_active": False}})
    )
    if r.matched_count == 0:
        return False
    connected_cache.put(chat_id, False)  # noqa: FBT003
    active_groups_cache.invalidate(_ALL_GROUPS_KEY)
    return True


async def active_groups() -> list[GroupDoc]:
    """Get all currently active and connected groups (L1->L2->DB cached)."""

    async def _fetch() -> list[GroupDoc]:
        return await db_call(
            _groups().find({"is_active": True}, {"_id": 0}).to_list(None)
        )

    return cast(
        "list[GroupDoc]",
        await active_groups_cache.get_or_fetch(_ALL_GROUPS_KEY, _fetch),
    )


async def active_group_count() -> int:
    """Count the number of currently active connected groups."""
    return await db_call(_groups().count_documents({"is_active": True}))


def with_primary_groups(
    groups: Sequence[GroupDoc],
    primary_ids: Iterable[int],
    *extra_ids: int,
) -> list[dict[str, Any]]:
    """Append primary/extra group entries missing from *groups*.

    Single owner for the "connected plus primaries" merge every
    federation-wide fan-out performs, so the dedup key and the
    synthesized entry shape cannot drift between the ban, mute, warn,
    unban, and appeal-approve paths. Falsy IDs (unset primaries) are
    skipped; callers pass ``(cfg.main_group, cfg.exec_group)`` plus any
    contextual chat such as the current one.
    """
    seen = {g.get("chat_id", 0) for g in groups}
    merged: list[dict[str, Any]] = [dict(g) for g in groups]
    for cid in (*primary_ids, *extra_ids):
        if not cid or cid in seen:
            continue
        seen.add(cid)
        merged.append({"chat_id": cid, "title": ""})
    return merged
