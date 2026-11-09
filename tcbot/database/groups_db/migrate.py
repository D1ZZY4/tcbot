# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Chat-migration repoint for group records."""

from __future__ import annotations

import asyncio

from pymongo.errors import DuplicateKeyError

from tcbot.database.cache import (
    _ALL_GROUPS_KEY,
    active_groups_cache,
    connected_cache,
)
from tcbot.database.mongos import db_call
from tcbot.utils.logger import get_logger

from .collections import _groups, _pending

log = get_logger("tcbot.database.groups_db")


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
    except DuplicateKeyError:
        # * The new chat already has a pending row: drop the stale old row
        # * so the migration converges instead of leaving a dangling
        # * pending_joins document referencing the old chat id.
        log.warning(
            "migrate_group (%d -> %d): pending target row exists, merging old row away",
            old_chat_id,
            new_chat_id,
        )
        try:
            await db_call(_pending().delete_one({"chat_id": old_chat_id}))
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception(
                "migrate_group (%d -> %d) pending stale-row cleanup failed",
                old_chat_id,
                new_chat_id,
            )
            pending_res = None
        else:
            pending_res = None
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
