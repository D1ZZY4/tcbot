# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Federated groups and pending joins collection helpers."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, cast

import cachetools as _cachetools
from pymongo.errors import DuplicateKeyError

from tcbot.database.cache import (
    _ALL_GROUPS_KEY,
    active_groups_cache,
    connected_cache,
)
from tcbot.database.documents import GroupDoc, PendingGroupDoc
from tcbot.database.mongos import col, db_call
from tcbot.utils.logger import get_logger
from tcbot.utils.time_and_date import utc_now

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence
    from typing import Any

    from motor.motor_asyncio import AsyncIOMotorCollection

log = get_logger(__name__)

# ─────────────────────── Collection Helpers ─────────────────────── #
# * Internal collection access utilities for groups database


def _groups() -> AsyncIOMotorCollection:
    return col("federated_groups")


def _pending() -> AsyncIOMotorCollection:
    return col("pending_joins")


# ──────────────────── Group Queries & Mutations ─────────────────── #
# * Functions to manage active connected groups in the federation
# * Includes caching to minimize database roundtrips
# ! CRITICAL: Cache invalidation is crucial here - always clear caches on changes


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


async def is_connected(chat_id: int) -> bool:
    """Check if a group is currently active and connected to the federation (L1->L2->DB cached)."""

    async def _fetch() -> bool:
        return (
            await db_call(
                _groups().find_one({"chat_id": chat_id, "is_active": True}, {"_id": 1})
            )
            is not None
        )

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


async def migrate_group(old_chat_id: int, new_chat_id: int) -> bool:
    """Update all group records from ``old_chat_id`` to ``new_chat_id`` after migration.

    Called when a basic group migrates to a supergroup. Updates both the
    ``federated_groups`` and ``pending_joins`` collections and invalidates
    the relevant cache entries. When the new chat already has a row (the
    unique ``chat_id`` index would reject the repoint), the stale old row
    is merged away instead of losing the migration. Returns ``True`` if
    any record was updated. Cancellation propagates.
    """
    try:
        group_res = await db_call(
            _groups().update_one(
                {"chat_id": old_chat_id},
                {"$set": {"chat_id": new_chat_id}},
            )
        )
    except asyncio.CancelledError:
        raise
    except DuplicateKeyError:
        # * The supergroup row already exists: drop the stale old row so
        # * the migration still converges instead of dying on the index.
        log.warning(
            "migrate_group (%d -> %d): target row exists, merging old row away",
            old_chat_id,
            new_chat_id,
        )
        try:
            await db_call(_groups().delete_one({"chat_id": old_chat_id}))
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception(
                "migrate_group (%d -> %d) stale-row cleanup failed",
                old_chat_id,
                new_chat_id,
            )
            return False
        group_res = None
    except Exception:
        log.exception(
            "migrate_group (%d -> %d) federated_groups update failed",
            old_chat_id,
            new_chat_id,
        )
        return False
    try:
        pending_res = await db_call(
            _pending().update_one(
                {"chat_id": old_chat_id},
                {"$set": {"chat_id": new_chat_id}},
            )
        )
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception(
            "migrate_group (%d -> %d) pending_joins update failed",
            old_chat_id,
            new_chat_id,
        )
        pending_res = None
    matched_any = (
        group_res is None
        or group_res.matched_count > 0
        or (pending_res is not None and pending_res.matched_count > 0)
    )
    group_matched = group_res is None or group_res.matched_count > 0
    if matched_any:
        connected_cache.put(old_chat_id, False)  # noqa: FBT003
        # * Only mark the new chat connected when its federated_groups row
        # * actually moved: a pending-only migration must not poison is_connected.
        if group_matched:
            connected_cache.put(new_chat_id, True)  # noqa: FBT003
            active_groups_cache.invalidate(_ALL_GROUPS_KEY)
    return matched_any


# ──────────────────── Pending Joins Management ──────────────────── #
# * Functions to manage groups waiting to be approved into the federation
# * Tracks join requests with all necessary metadata


async def add_pending(chat_id: int, title: str, owner_id: int, message_id: int) -> None:
    """Add or update a pending join request from a group."""
    await db_call(
        _pending().update_one(
            {"chat_id": chat_id},
            {
                "$set": {
                    "chat_id": chat_id,
                    "title": title,
                    "owner_id": owner_id,
                    "message_id": message_id,
                    "added_date": utc_now(),
                }
            },
            upsert=True,
        )
    )


async def get_pending(chat_id: int) -> PendingGroupDoc | None:
    """Get a pending join request by chat ID."""
    return await db_call(_pending().find_one({"chat_id": chat_id}))


async def remove_pending(chat_id: int) -> None:
    """Remove a pending join request after it's approved or rejected."""
    await db_call(_pending().delete_one({"chat_id": chat_id}))


# ───────────────────── Group Locale Preferences ─────────────────── #
# * Stored on the federated_groups row itself: locale rides alongside
# * the group with no extra collection, and reads filter on the already
# * indexed chat_id. No upsert here: only connected groups hold settings.
# * L1 for locale reads: resolution runs on every group command, so hits
# * must cost no I/O. Writes invalidate; TTL bounds staleness when
# * another process changes the row. Unset (None) caches too.
_GROUP_LOCALE_L1: _cachetools.TTLCache = _cachetools.TTLCache(maxsize=1024, ttl=300)


async def get_group_locale(chat_id: int) -> str | None:
    """Return the stored locale code for a group, or None when unset."""
    try:
        return _GROUP_LOCALE_L1[chat_id]
    except KeyError:
        pass
    doc = await db_call(
        _groups().find_one({"chat_id": chat_id}, {"_id": 0, "locale": 1})
    )
    if not doc:
        _GROUP_LOCALE_L1[chat_id] = None
        return None
    locale = doc.get("locale")
    value = locale if isinstance(locale, str) and locale else None
    _GROUP_LOCALE_L1[chat_id] = value
    return value


async def set_group_locale(chat_id: int, locale: str | None) -> bool:
    """Store a group locale, or clear it when ``locale`` is None.

    Returns True when a group row was matched. Locale codes are stored
    verbatim; validity is enforced by the caller and at resolution time.
    """
    if locale is None:
        result = await db_call(
            _groups().update_one({"chat_id": chat_id}, {"$unset": {"locale": ""}})
        )
    else:
        result = await db_call(
            _groups().update_one({"chat_id": chat_id}, {"$set": {"locale": locale}})
        )
    _GROUP_LOCALE_L1.pop(chat_id, None)
    return result.matched_count > 0
