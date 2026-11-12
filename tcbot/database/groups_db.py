# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Federated groups and pending joins collection helpers."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, cast

import cachetools as _cachetools
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError

from tcbot.database.base import federated_groups, pending_joins
from tcbot.database.cache import (
    _ALL_GROUPS_KEY,
    active_groups_cache,
    connected_cache,
)
from tcbot.database.documents import GroupDoc, PendingGroupDoc
from tcbot.database.engine import (
    constraint_name,
    db_call,
    fetch_all,
    fetch_one,
    fetch_value,
    run,
    run_transaction,
)
from tcbot.utils.logger import get_logger
from tcbot.utils.time_and_date import utc_now

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence
    from typing import Any

    from sqlalchemy.ext.asyncio import AsyncSession

log = get_logger(__name__)

# ──────────────────────────── Tables ────────────────────────────── #
# * Both tables are keyed by the chat id, so a row is its own document:
# * there is no surrogate id to hide from the returned records.
_GROUP_COLUMNS = list(federated_groups.c)
_PENDING_COLUMNS = list(pending_joins.c)

# * Names of the primary keys that can reject a chat repoint. PostgreSQL
# * names an unnamed primary key constraint after its table.
_CONSTRAINT_GROUPS_PKEY: str = "federated_groups_pkey"
_CONSTRAINT_PENDING_PKEY: str = "pending_joins_pkey"


def _is_chat_key_violation(exc: IntegrityError, expected: str) -> bool:
    """Return True when the failure is the chat id primary-key conflict.

    The chat id is the only unique key of both tables, so a repoint can
    only collide with the row that already owns the target chat. A driver
    that reports no constraint name leaves no other candidate.
    """
    name = constraint_name(exc)
    return not name or name == expected


# ─────────────────────── Connected groups ────────────────────── #


async def get_group_titles(chat_ids: list[int]) -> dict[int, str]:
    """Return {chat_id: title} for the given chat_ids; missing groups are absent."""
    if not chat_ids:
        return {}
    rows = await db_call(
        lambda: fetch_all(
            select(federated_groups.c.chat_id, federated_groups.c.title).where(
                federated_groups.c.chat_id.in_(chat_ids)
            )
        )
    )
    return {int(d["chat_id"]): d.get("title") or str(d["chat_id"]) for d in rows}


async def refresh_group_title(chat_id: int, title: str) -> bool:
    """Update the stored title when live Telegram reports a different one.

    Returns True when a change was written (and the groups cache
    invalidated), False when already current or the group is unknown.
    Single atomic update: the filter skips the write when the
    stored title already matches, so the common no-change path costs one
    round trip instead of two and a concurrent refresh cannot clobber a
    newer title with a stale read.
    """
    affected = await db_call(
        lambda: run(
            federated_groups.update()
            .where(
                federated_groups.c.chat_id == chat_id,
                federated_groups.c.title != title,
            )
            .values(title=title)
        )
    )
    if affected == 0:
        return False
    active_groups_cache.invalidate(_ALL_GROUPS_KEY)
    return True


async def is_connected(chat_id: int, *, fresh: bool = False) -> bool:
    """Check if a group is currently active and connected to the federation (L1->L2->DB cached).

    With ``fresh=True`` the cache is bypassed and the row is read directly
    from the database, then the cache is refreshed. The origin guard uses
    ``fresh=True`` so a disconnect in another process is never hidden for
    up to the 120 s connection TTL; display reads keep the cached path.
    """

    async def _fetch() -> bool:
        row = await db_call(
            lambda: fetch_one(
                select(federated_groups.c.chat_id).where(
                    federated_groups.c.chat_id == chat_id,
                    federated_groups.c.is_active.is_(True),
                )
            )
        )
        return row is not None

    if fresh:
        connected = await _fetch()
        connected_cache.put(chat_id, connected)
        return connected
    return cast("bool", await connected_cache.get_or_fetch(chat_id, _fetch))


async def add_group(chat_id: int, title: str, added_by: int) -> None:
    """Add or update a group in the federated_groups table."""
    now = utc_now()
    await db_call(
        lambda: run(
            pg_insert(federated_groups)
            .values(
                chat_id=chat_id,
                title=title,
                added_by=added_by,
                is_active=True,
                added_date=now,
            )
            .on_conflict_do_update(
                index_elements=["chat_id"],
                # * First-connect date must survive re-adds and title
                # * refreshes: stats shows it as the join date, so it stays
                # * out of the conflict update instead of rewriting history
                # * on every add.
                set_={"title": title, "added_by": added_by, "is_active": True},
            )
        )
    )
    connected_cache.put(chat_id, True)  # noqa: FBT003
    active_groups_cache.invalidate(_ALL_GROUPS_KEY)


async def deactivate_group(chat_id: int) -> bool:
    """Mark a group as inactive (disconnect from federation)."""
    affected = await db_call(
        lambda: run(
            federated_groups.update()
            .where(federated_groups.c.chat_id == chat_id)
            .values(is_active=False)
        )
    )
    if affected == 0:
        return False
    connected_cache.put(chat_id, False)  # noqa: FBT003
    active_groups_cache.invalidate(_ALL_GROUPS_KEY)
    return True


async def active_groups() -> list[GroupDoc]:
    """Get all currently active and connected groups (L1->L2->DB cached)."""

    async def _fetch() -> list[GroupDoc]:
        rows = await db_call(
            lambda: fetch_all(
                select(*_GROUP_COLUMNS).where(federated_groups.c.is_active.is_(True))
            )
        )
        return cast("list[GroupDoc]", rows)

    return cast(
        "list[GroupDoc]",
        await active_groups_cache.get_or_fetch(_ALL_GROUPS_KEY, _fetch),
    )


async def active_group_count() -> int:
    """Count the number of currently active connected groups."""
    total = await db_call(
        lambda: fetch_value(
            select(func.count())
            .select_from(federated_groups)
            .where(federated_groups.c.is_active.is_(True))
        )
    )
    return int(total or 0)


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
    skipped; callers pass ``(cfg.main_group,)`` plus any contextual chat
    such as the current one.
    """
    seen = {g.get("chat_id", 0) for g in groups}
    merged: list[dict[str, Any]] = [dict(g) for g in groups]
    for cid in (*primary_ids, *extra_ids):
        if not cid or cid in seen:
            continue
        seen.add(cid)
        merged.append({"chat_id": cid, "title": ""})
    return merged


# ───────────────────────── Group locale ────────────────────────── #

# * Stored on the federated_groups row itself: locale rides alongside
# * the group with no extra table, and reads filter on the already
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
    row = await db_call(
        lambda: fetch_one(
            select(federated_groups.c.locale).where(
                federated_groups.c.chat_id == chat_id
            )
        )
    )
    if row is None:
        _GROUP_LOCALE_L1[chat_id] = None
        return None
    locale = row.get("locale")
    value = locale if isinstance(locale, str) and locale else None
    _GROUP_LOCALE_L1[chat_id] = value
    return value


async def set_group_locale(chat_id: int, locale: str | None) -> bool:
    """Store a group locale, or clear it when ``locale`` is None.

    Returns True when a group row was matched. Locale codes are stored
    verbatim; validity is enforced by the caller and at resolution time.
    """
    if locale is None:
        affected = await db_call(
            lambda: run(
                federated_groups.update()
                .where(federated_groups.c.chat_id == chat_id)
                .values(locale=None)
            )
        )
    else:
        affected = await db_call(
            lambda: run(
                federated_groups.update()
                .where(federated_groups.c.chat_id == chat_id)
                .values(locale=locale)
            )
        )
    _GROUP_LOCALE_L1.pop(chat_id, None)
    # * active_groups() returns the row including its locale; without this
    # * the new locale stays stale for the groups-list TTL after a change.
    active_groups_cache.invalidate(_ALL_GROUPS_KEY)
    return affected > 0


# ────────────────────────── Pending joins ──────────────────────── #


async def add_pending(chat_id: int, title: str, owner_id: int, message_id: int) -> None:
    """Add or update a pending join request from a group."""
    now = utc_now()
    await db_call(
        lambda: run(
            pg_insert(pending_joins)
            .values(
                chat_id=chat_id,
                title=title,
                owner_id=owner_id,
                message_id=message_id,
                added_date=now,
            )
            .on_conflict_do_update(
                index_elements=["chat_id"],
                set_={
                    "title": title,
                    "owner_id": owner_id,
                    "message_id": message_id,
                    "added_date": now,
                },
            )
        )
    )


async def get_pending(chat_id: int) -> PendingGroupDoc | None:
    """Get a pending join request by chat ID."""
    row = await db_call(
        lambda: fetch_one(
            select(*_PENDING_COLUMNS).where(pending_joins.c.chat_id == chat_id)
        )
    )
    return cast("PendingGroupDoc | None", row)


async def remove_pending(chat_id: int) -> None:
    """Remove a pending join request after it's approved or rejected."""
    await db_call(
        lambda: run(pending_joins.delete().where(pending_joins.c.chat_id == chat_id))
    )


# ─────────────────────────── Migration ─────────────────────────── #


async def _merge_group_row(old_chat_id: int, new_chat_id: int) -> None:
    """Fold a stale group row into the row that already owns the new chat id.

    The repoint cannot update the primary key in place because the target
    row already exists, so the stale row is merged away instead. The
    merge carries the old row's group locale over to the surviving row
    when the survivor has none: a group that chose its language before
    the migration keeps it.
    """

    async def _work(sess: AsyncSession) -> None:
        old_row = (
            (
                await sess.execute(
                    select(federated_groups.c.locale).where(
                        federated_groups.c.chat_id == old_chat_id
                    )
                )
            )
            .mappings()
            .first()
        )
        if old_row is None:
            return
        target_locale = (
            (
                await sess.execute(
                    select(federated_groups.c.locale).where(
                        federated_groups.c.chat_id == new_chat_id
                    )
                )
            )
            .mappings()
            .first()
        )
        if target_locale is not None and target_locale["locale"] is None:
            await sess.execute(
                federated_groups.update()
                .where(federated_groups.c.chat_id == new_chat_id)
                .values(locale=old_row["locale"])
            )
        await sess.execute(
            federated_groups.delete().where(federated_groups.c.chat_id == old_chat_id)
        )

    await run_transaction(_work)


async def _group_is_active(chat_id: int) -> bool:
    """Return whether the connected-group row of *chat_id* is active."""
    row = await db_call(
        lambda: fetch_one(
            select(federated_groups.c.is_active).where(
                federated_groups.c.chat_id == chat_id
            )
        )
    )
    return bool(row and row.get("is_active"))


async def migrate_group(old_chat_id: int, new_chat_id: int) -> bool:
    """Update all group records from ``old_chat_id`` to ``new_chat_id`` after migration.

    Called when a basic group migrates to a supergroup. Updates both the
    ``federated_groups`` and ``pending_joins`` tables and invalidates
    the relevant cache entries. When the new chat already has a row (the
    unique ``chat_id`` key would reject the repoint), the stale old row
    is merged away instead of losing the migration. Returns ``True`` if
    any record was updated. Cancellation propagates.
    """
    try:
        group_affected = await db_call(
            lambda: run(
                federated_groups.update()
                .where(federated_groups.c.chat_id == old_chat_id)
                .values(chat_id=new_chat_id)
            )
        )
        group_matched = group_affected > 0
    except asyncio.CancelledError:
        raise
    except IntegrityError as exc:
        if not _is_chat_key_violation(exc, _CONSTRAINT_GROUPS_PKEY):
            log.exception(
                "migrate_group (%d -> %d) federated_groups update failed",
                old_chat_id,
                new_chat_id,
            )
            return False
        # * The supergroup row already exists: merge the stale old row away
        # * so the migration still converges instead of dying on the key.
        log.warning(
            "migrate_group (%d -> %d): target row exists, merging old row away",
            old_chat_id,
            new_chat_id,
        )
        try:
            await _merge_group_row(old_chat_id, new_chat_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception(
                "migrate_group (%d -> %d) stale-row cleanup failed",
                old_chat_id,
                new_chat_id,
            )
            return False
        group_matched = True
    except Exception:
        log.exception(
            "migrate_group (%d -> %d) federated_groups update failed",
            old_chat_id,
            new_chat_id,
        )
        return False
    try:
        pending_affected = await db_call(
            lambda: run(
                pending_joins.update()
                .where(pending_joins.c.chat_id == old_chat_id)
                .values(chat_id=new_chat_id)
            )
        )
    except asyncio.CancelledError:
        raise
    except IntegrityError as exc:
        if not _is_chat_key_violation(exc, _CONSTRAINT_PENDING_PKEY):
            log.exception(
                "migrate_group (%d -> %d) pending_joins update failed",
                old_chat_id,
                new_chat_id,
            )
            pending_affected = None
        else:
            # * The new chat already has a pending row: drop the stale old row
            # * so the migration converges instead of leaving a dangling
            # * pending_joins record referencing the old chat id.
            log.warning(
                "migrate_group (%d -> %d): pending target row exists, merging old row away",
                old_chat_id,
                new_chat_id,
            )
            try:
                await db_call(
                    lambda: run(
                        pending_joins.delete().where(
                            pending_joins.c.chat_id == old_chat_id
                        )
                    )
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception(
                    "migrate_group (%d -> %d) pending stale-row cleanup failed",
                    old_chat_id,
                    new_chat_id,
                )
            pending_affected = None
    except Exception:
        log.exception(
            "migrate_group (%d -> %d) pending_joins update failed",
            old_chat_id,
            new_chat_id,
        )
        pending_affected = None
    matched_any = group_matched or (
        pending_affected is not None and pending_affected > 0
    )
    if matched_any:
        connected_cache.put(old_chat_id, False)  # noqa: FBT003
        # * Only mark the new chat when its federated_groups row actually
        # * moved: a pending-only migration must not poison is_connected.
        if group_matched:
            # * The cached value mirrors the row that survived. The target
            # * row may be an inactive one (a group the operator
            # * disconnected), so caching "connected" unconditionally would
            # * report a disconnected group as connected for the whole
            # * cache TTL and pull it into the federation fan-outs.
            connected_cache.put(new_chat_id, await _group_is_active(new_chat_id))
            active_groups_cache.invalidate(_ALL_GROUPS_KEY)
    return matched_any
