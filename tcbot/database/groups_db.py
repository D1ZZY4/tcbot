# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Connected group registry, group configuration, and join requests."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

import cachetools as _cachetools
from sqlalchemy import func, or_, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from tcbot.database.base import (
    chat_settings,
    connected_chats,
    join_requests,
    telegram_chats,
)
from tcbot.database.cache import (
    _ALL_GROUPS_KEY,
    active_groups_cache,
    connected_cache,
)
from tcbot.database.documents import GroupDoc, PendingGroupDoc
from tcbot.database.engine import (
    db_call,
    fetch_all,
    fetch_one,
    fetch_value,
    run,
    run_transaction,
)
from tcbot.database.types import ChatId, GroupId, UserId
from tcbot.database.users_cache import ensure_users
from tcbot.utils.logger import get_logger
from tcbot.utils.time_and_date import utc_now

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence
    from datetime import datetime

    from sqlalchemy.ext.asyncio import AsyncSession

log = get_logger(__name__)

# ──────────────────────────── Tables ────────────────────────────── #
# * The registry, the identity, the configuration, and the request are
# * four tables: the registry holds the connection, the identity holds
# * the Telegram profile, the configuration holds the settings, and the
# * request holds the pending decision.
_GROUP_COLUMNS = (
    connected_chats.c.chat_id,
    connected_chats.c.added_by_user_id,
    connected_chats.c.added_at,
    connected_chats.c.is_active,
    telegram_chats.c.title,
    chat_settings.c.locale,
)
_PENDING_COLUMNS = (
    join_requests.c.chat_id,
    join_requests.c.owner_user_id,
    join_requests.c.request_message_id,
    join_requests.c.status,
    join_requests.c.requested_at,
    join_requests.c.id,
)


def _group_row(docs: list[dict[str, Any]]) -> list[GroupDoc]:
    """Return the group documents with the column names the callers read."""
    return [
        GroupDoc(
            chat_id=cast("GroupId", doc["chat_id"]),
            title=doc.get("title") or "Unknown",
            added_by=cast("UserId", doc.get("added_by_user_id") or 0),
            added_date=cast("datetime", doc["added_at"]),
            is_active=bool(doc.get("is_active")),
            locale=doc.get("locale"),
        )
        for doc in docs
    ]


# ─────────────────────── Connected groups ────────────────────── #


async def get_group_titles(chat_ids: list[int]) -> dict[int, str]:
    """Return {chat_id: title} for the given chat_ids; missing groups are absent."""
    if not chat_ids:
        return {}
    rows = await db_call(
        lambda: fetch_all(
            select(telegram_chats.c.chat_id, telegram_chats.c.title).where(
                telegram_chats.c.chat_id.in_(chat_ids)
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
            telegram_chats.update()
            .where(
                telegram_chats.c.chat_id == chat_id,
                # * A stored NULL never matches ``!= title``: SQL NULL
                # * comparisons yield NULL. The primary group is registered
                # * with no title at boot, so its title must be fillable.
                or_(
                    telegram_chats.c.title.is_(None),
                    telegram_chats.c.title != title,
                ),
            )
            .values(title=title, updated_at=utc_now())
        )
    )
    if affected == 0:
        return False
    active_groups_cache.invalidate(_ALL_GROUPS_KEY)
    return True


async def is_connected(chat_id: int, *, fresh: bool = False) -> bool:
    """Check if a group is currently active and connected to the community (L1->L2->DB cached).

    With ``fresh=True`` the cache is bypassed and the row is read directly
    from the database, then the cache is refreshed. The origin guard uses
    ``fresh=True`` so a disconnect in another process is never hidden for
    up to the 120 s connection TTL; display reads keep the cached path.
    """

    async def _fetch() -> bool:
        row = await db_call(
            lambda: fetch_one(
                select(connected_chats.c.chat_id).where(
                    connected_chats.c.chat_id == chat_id,
                    connected_chats.c.is_active.is_(True),
                )
            )
        )
        return row is not None

    if fresh:
        # * refresh() republishes only when the key was not invalidated while
        # * the read was in flight, so a concurrent disconnect cannot be
        # * overwritten by the older connected value.
        return await connected_cache.refresh(chat_id, _fetch)
    return cast("bool", await connected_cache.get_or_fetch(chat_id, _fetch))


async def ensure_primary_group(chat_id: int, title: str | None = None) -> None:
    """Register a primary group as a managed chat without a connect prompt.

    A primary group is a required enforcement destination, but it is not
    connected through the join flow. The moderation schema nevertheless
    requires chat-scoped decisions to name an active connected chat, so the
    primary group needs a registry row of its own. The row is active, like
    a connected group, and the regular connect path still refuses to
    create it. The title is only written when the caller has one.
    """
    if not chat_id:
        return

    async def _work(sess: AsyncSession) -> None:
        chat_stmt = pg_insert(telegram_chats).values(
            chat_id=chat_id,
            chat_type="supergroup",
            title=title,
        )
        if title is None:
            chat_stmt = chat_stmt.on_conflict_do_nothing(index_elements=["chat_id"])
        else:
            chat_stmt = chat_stmt.on_conflict_do_update(
                index_elements=["chat_id"],
                set_={"title": title, "updated_at": utc_now()},
            )
        await sess.execute(chat_stmt)
        await sess.execute(
            pg_insert(connected_chats)
            .values(chat_id=chat_id, is_active=True)
            .on_conflict_do_update(
                index_elements=["chat_id"],
                set_={"is_active": True},
            )
        )

    await run_transaction(_work)
    connected_cache.put(chat_id, True)  # noqa: FBT003
    active_groups_cache.invalidate(_ALL_GROUPS_KEY)


async def ensure_destinations(
    destinations: Iterable[tuple[int, bool]],
) -> None:
    """Register the configured log and evidence destinations as chat rows.

    A channel the bot posts to is not a connected group, so nothing else
    creates its ``telegram_chats`` row. The evidence archive and the run
    targets reference that table, and a fresh deployment would fail its
    first ban on an unregistered proof channel. Existing rows keep their
    type: a destination that is also a managed group is not rewritten.
    """
    rows = [
        {
            "chat_id": chat_id,
            "chat_type": "supergroup" if is_forum else "channel",
            "is_forum": is_forum,
        }
        for chat_id, is_forum in dict.fromkeys(
            (int(chat_id), bool(is_forum))
            for chat_id, is_forum in destinations
            if chat_id and int(chat_id) < 0
        )
    ]
    if not rows:
        return

    async def _work(sess: AsyncSession) -> None:
        await sess.execute(
            pg_insert(telegram_chats)
            .values(rows)
            .on_conflict_do_nothing(index_elements=["chat_id"])
        )

    await run_transaction(_work)


async def add_group(chat_id: int, title: str, added_by: int) -> None:
    """Connect a group to the community."""
    now = utc_now()

    async def _work(sess: AsyncSession) -> None:
        # * The registry references the account that connected the group.
        # * The owner may be connecting a group before the member cache has
        # * seen them, so the identity row is created with the connection.
        await ensure_users(sess, added_by)
        await sess.execute(
            pg_insert(telegram_chats)
            .values(
                chat_id=chat_id,
                chat_type="supergroup",
                title=title,
                created_at=now,
                updated_at=now,
            )
            .on_conflict_do_update(
                index_elements=["chat_id"],
                set_={"title": title, "updated_at": now},
            )
        )
        await sess.execute(
            pg_insert(connected_chats)
            .values(
                chat_id=chat_id,
                added_by_user_id=added_by,
                added_at=now,
                is_active=True,
            )
            .on_conflict_do_update(
                index_elements=["chat_id"],
                # * First-connect date must survive re-adds and title
                # * refreshes: stats shows it as the join date, so it stays
                # * out of the conflict update instead of rewriting history
                # * on every add.
                set_={"added_by_user_id": added_by, "is_active": True},
            )
        )

    await run_transaction(_work)
    connected_cache.put(chat_id, True)  # noqa: FBT003
    active_groups_cache.invalidate(_ALL_GROUPS_KEY)


async def deactivate_group(chat_id: int) -> bool:
    """Disconnect a group from the community.

    The row stays in the registry: the moderation history refers to the
    group, so a disconnect must not remove the identity.
    """
    affected = await db_call(
        lambda: run(
            connected_chats.update()
            .where(connected_chats.c.chat_id == chat_id)
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
                select(*_GROUP_COLUMNS)
                .select_from(connected_chats)
                .join(
                    telegram_chats,
                    telegram_chats.c.chat_id == connected_chats.c.chat_id,
                )
                .outerjoin(
                    chat_settings, chat_settings.c.chat_id == connected_chats.c.chat_id
                )
                .where(connected_chats.c.is_active.is_(True))
            )
        )
        return _group_row(rows)

    return cast(
        "list[GroupDoc]",
        await active_groups_cache.get_or_fetch(_ALL_GROUPS_KEY, _fetch),
    )


async def active_group_count() -> int:
    """Count the number of currently active connected groups."""
    total = await db_call(
        lambda: fetch_value(
            select(func.count())
            .select_from(connected_chats)
            .where(connected_chats.c.is_active.is_(True))
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
    community-wide fan-out performs, so the dedup key and the
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
# * The locale lives in the group configuration, not in the registry:
# * the registry holds the connection, the configuration holds the
# * settings. Reads filter on the already indexed chat_id.
# * L1 for locale reads: resolution runs on every group command, so hits
# * must cost no I/O. Writes invalidate; TTL bounds staleness when
# * another process changes the row. Unset (None) caches too.
_GROUP_LOCALE_L1: _cachetools.TTLCache = _cachetools.TTLCache(maxsize=1024, ttl=300)
# * Generation per chat: a read that started before a locale write must not
# * put the old value back into L1 after the write invalidated it.
_GROUP_LOCALE_GEN: _cachetools.TTLCache = _cachetools.TTLCache(maxsize=4096, ttl=3600)


def _bump_locale_generation(chat_id: int) -> None:
    """Advance the locale generation of one chat after a write."""
    _GROUP_LOCALE_GEN[chat_id] = int(_GROUP_LOCALE_GEN.get(chat_id, 0)) + 1


async def get_group_locale(chat_id: int) -> str | None:
    """Return the stored locale code for a group, or None when unset."""
    try:
        return _GROUP_LOCALE_L1[chat_id]
    except KeyError:
        pass
    generation = int(_GROUP_LOCALE_GEN.get(chat_id, 0))
    row = await db_call(
        lambda: fetch_one(
            select(chat_settings.c.locale).where(chat_settings.c.chat_id == chat_id)
        )
    )
    locale = row.get("locale") if row is not None else None
    value = locale if isinstance(locale, str) and locale else None
    # * Publish only when no write invalidated the chat while the read was
    # * in flight; otherwise the stale locale would live for the whole TTL.
    if int(_GROUP_LOCALE_GEN.get(chat_id, 0)) == generation:
        _GROUP_LOCALE_L1[chat_id] = value
    return value


async def set_group_locale(chat_id: int, locale: str | None) -> bool:
    """Store a group locale, or clear it when ``locale`` is None.

    Returns True when a group row was matched. Locale codes are stored
    verbatim; validity is enforced by the caller and at resolution time.
    """
    affected = await db_call(
        lambda: run(
            chat_settings.update()
            .where(chat_settings.c.chat_id == chat_id)
            .values(locale=locale, updated_at=utc_now())
        )
    )
    _bump_locale_generation(chat_id)
    _GROUP_LOCALE_L1.pop(chat_id, None)
    # * active_groups() returns the row including its locale; without this
    # * the new locale stays stale for the groups-list TTL after a change.
    active_groups_cache.invalidate(_ALL_GROUPS_KEY)
    return affected > 0


# ────────────────────────── Pending joins ──────────────────────── #


async def add_pending(chat_id: int, title: str, owner_id: int, message_id: int) -> None:
    """Record the join request of a group.

    ``owner_id`` is the account that added the bot when Telegram names one.
    An anonymous admin add names no real account, so the caller passes ``0``
    and the row stores ``NULL`` instead of violating the user foreign key.
    The group creator still decides from the prompt.
    """
    now = utc_now()

    async def _work(sess: AsyncSession) -> None:
        # * The request references the account that asked to connect. An
        # * anonymous add passes 0, which names no account and stays NULL.
        await ensure_users(sess, owner_id)
        await sess.execute(
            pg_insert(telegram_chats)
            .values(
                chat_id=chat_id,
                chat_type="supergroup",
                title=title,
                created_at=now,
                updated_at=now,
            )
            .on_conflict_do_update(
                index_elements=["chat_id"],
                set_={"title": title, "updated_at": now},
            )
        )
        await sess.execute(
            pg_insert(join_requests)
            .values(
                chat_id=chat_id,
                owner_user_id=owner_id if owner_id > 0 else None,
                request_message_id=message_id,
                status="pending",
                requested_at=now,
            )
            # * The request facts are immutable, so an open request is
            # * kept as it is: a second request for the same chat reuses
            # * the open one instead of rewriting who asked for it and
            # * when.
            .on_conflict_do_nothing(
                index_elements=["chat_id"],
                index_where=join_requests.c.status == "pending",
            )
        )

    await run_transaction(_work)
    # * The pending write also refreshes the chat title, which the active
    # * group listing renders.
    active_groups_cache.invalidate(_ALL_GROUPS_KEY)


async def get_pending(chat_id: int) -> PendingGroupDoc | None:
    """Get the open join request of a chat."""
    row = await db_call(
        lambda: fetch_one(
            select(*_PENDING_COLUMNS).where(
                join_requests.c.chat_id == chat_id,
                join_requests.c.status == "pending",
            )
        )
    )
    if row is None:
        return None
    title_row = await db_call(
        lambda: fetch_one(
            select(telegram_chats.c.title).where(telegram_chats.c.chat_id == chat_id)
        )
    )
    return PendingGroupDoc(
        chat_id=cast("ChatId", row["chat_id"]),
        title=(title_row or {}).get("title") or "",
        owner_id=cast("UserId", row.get("owner_user_id") or 0),
        message_id=row.get("request_message_id") or 0,
        added_date=cast("datetime", row["requested_at"]),
        request_id=int(row["id"]),
        status="pending",
    )


async def remove_pending(chat_id: int) -> None:
    """Close the join request of a chat after it was approved or rejected."""
    await db_call(
        lambda: run(
            join_requests.update()
            .where(
                join_requests.c.chat_id == chat_id,
                join_requests.c.status == "pending",
            )
            .values(status="cancelled", resolved_at=utc_now())
        )
    )


# ─────────────────────────── Migration ─────────────────────────── #


async def _group_is_active(chat_id: int) -> bool:
    """Return whether the connected-group row of *chat_id* is active."""
    row = await db_call(
        lambda: fetch_one(
            select(connected_chats.c.is_active).where(
                connected_chats.c.chat_id == chat_id
            )
        )
    )
    return bool(row and row.get("is_active"))


async def migrate_group(old_chat_id: int, new_chat_id: int) -> bool:
    """Repoint every group record from ``old_chat_id`` to ``new_chat_id``.

    Called when a basic group migrates to a supergroup. Telegram retires
    the old chat id and hands the bot the id of the supergroup that
    replaced it, so the identity, the configuration, the registry, the
    membership, the open request, and the decisions of that group have to
    follow the new id.

    The move runs as one database transaction: the decisions point at the
    connected group, so the new registry row has to exist before the
    decisions move, and a half-moved group would be worse than one that
    did not move at all. The old chat stays known but inactive, so the
    history that refers to it stays readable.

    Returns ``True`` when the group was connected and has been moved.
    Cancellation propagates.
    """
    summary = await db_call(
        lambda: fetch_one(
            text(
                "SELECT (repoint_chat_records(:old_chat_id, :new_chat_id)"
                " ->> 'was_active')::boolean AS was_active"
            ).bindparams(
                old_chat_id=old_chat_id,
                new_chat_id=new_chat_id,
            )
        )
    )
    if summary is None:
        return False
    moved = bool(summary.get("was_active"))
    connected_cache.put(old_chat_id, False)  # noqa: FBT003
    # * The cached value mirrors the row, not the move. The move may have
    # * created the row of the new chat, and a row that already existed
    # * keeps its own state, so caching "connected" unconditionally would
    # * report a disconnected group as connected for the whole cache TTL
    # * and pull it into the community fan-outs.
    connected_cache.put(new_chat_id, await _group_is_active(new_chat_id))
    active_groups_cache.invalidate(_ALL_GROUPS_KEY)
    # * The locale cache is keyed by chat id; both ids moved.
    _bump_locale_generation(old_chat_id)
    _bump_locale_generation(new_chat_id)
    _GROUP_LOCALE_L1.pop(old_chat_id, None)
    _GROUP_LOCALE_L1.pop(new_chat_id, None)
    return moved
