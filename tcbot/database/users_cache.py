# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Telegram user profile helpers (telegram_users table only)."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, cast

from sqlalchemy import bindparam, func, literal, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError

from tcbot.database.base import chat_members, telegram_users
from tcbot.database.cache import CACHE_MISS, user_mention_cache
from tcbot.database.documents import UserDoc
from tcbot.database.engine import (
    constraint_name,
    db_call,
    fetch_all,
    fetch_one,
    fetch_value,
    run,
)
from tcbot.utils.time_and_date import utc_now

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

# ──────────────────────────── Table ────────────────────────────── #
# * The stored columns are the ones the profile carries. The lowercase
# * form of the searchable fields is an index helper, not a column.
_USER_COLUMNS = [
    telegram_users.c.user_id,
    telegram_users.c.username,
    telegram_users.c.first_name,
    telegram_users.c.last_name,
    telegram_users.c.language_code,
    telegram_users.c.first_seen_at,
    telegram_users.c.last_seen_at,
    telegram_users.c.created_at,
    telegram_users.c.updated_at,
    # * Readers need the erasure marker to avoid re-verifying a cleared
    # * profile against live Telegram and caching the recovered identity.
    telegram_users.c.erased_at,
]

# * L1 mention-cache entries are [first_name, username, last_name] triples.
# * Readers only use indexes 0 and 1; index 2 exists so change detection
# * notices last_name-only updates. The not-found sentinel is all-None.
_NOT_FOUND_SENTINEL: list[str | None] = [None, None, None]

_SEL_USER_BY_ID = select(*_USER_COLUMNS).where(
    telegram_users.c.user_id == bindparam("user_id")
)
_SEL_MENTION_TRIPLE = select(
    telegram_users.c.first_name,
    telegram_users.c.username,
    telegram_users.c.last_name,
).where(telegram_users.c.user_id == bindparam("user_id"))
_SEL_TOTAL_USERS = select(func.count()).select_from(telegram_users)
_SEL_BY_USERNAME = (
    select(telegram_users.c.user_id, telegram_users.c.first_name)
    .where(func.lower(telegram_users.c.username) == bindparam("needle"))
    .limit(1)
)


def _cached_triple(data: list[str | None]) -> tuple[str | None, str | None, str | None]:
    """Split a cache entry into (first_name, username, last_name).

    Legacy L2 pairs stored before last_name tracking have length 2; the
    missing element reads as None, which correctly counts as changed.
    """
    return (
        data[0] if len(data) > 0 else None,
        data[1] if len(data) > 1 else None,
        data[2] if len(data) > 2 else None,
    )


async def _fetch_mention_triple(user_id: int) -> list[str | None]:
    """Read (first_name, username, last_name) for the mention cache.

    Single owner for the projection and the not-found sentinel so the
    cached mention readers cannot drift apart.
    """
    doc = await db_call(lambda: fetch_one(_SEL_MENTION_TRIPLE.params(user_id=user_id)))
    if doc:
        return [
            doc.get("first_name") or str(user_id),
            doc.get("username"),
            doc.get("last_name"),
        ]
    # * Sentinel: user has no telegram_users row. All-None is used
    # * (not [str(user_id), None, None]) so the not-found case is unambiguous:
    # * a real first_name is never None, but str(user_id) could coincide
    # * with an actual numeric display name and would suppress fallback.
    return list(_NOT_FOUND_SENTINEL)


def is_placeholder_name(name: str | None) -> bool:
    """Return True when the name is a fallback rather than a real name.

    Two fallback shapes exist in the profile cache: a bare numeric ID and the
    legacy ``User <id>`` form older releases wrote. A view that renders
    either as a name shows the placeholder to the operator, so every
    surface must agree on what counts as a real name.
    """
    if not name:
        return True
    stripped = name.strip()
    return stripped.startswith("User ") or stripped.lstrip("-").isdigit()


# ────────────────────────────── Reads ────────────────────────────── #


async def get_user(user_id: int) -> UserDoc | None:
    """Get the full stored profile for a specific user."""
    row = await db_call(lambda: fetch_one(_SEL_USER_BY_ID.params(user_id=user_id)))
    return cast("UserDoc | None", row)


async def get_user_mention_data(user_id: int) -> tuple[str, str | None]:
    """Return (first_name, username) for mention formatting (L1->L2->DB cached).

    Uses ``user_mention_cache`` (Redis-backed TwoLevelCache) to avoid database
    round-trips on repeated lookups.  Cache is invalidated on every ``upsert_user``.

    Cache sentinel: ``[None, None, None]`` is stored when the user has no row in
    ``telegram_users``.  The consumer converts ``None`` → ``str(user_id)`` so the
    returned tuple always contains a non-empty string as the first element.
    """

    async def _fetch() -> list[str | None]:
        return await _fetch_mention_triple(user_id)

    data = await user_mention_cache.get_or_fetch(user_id, _fetch)
    # * data[0] is None when the user has no telegram_users row (sentinel).
    name = cast("str", data[0]) if data[0] is not None else str(user_id)
    return (name, data[1])


async def _mention_triples(
    user_ids: list[int],
) -> dict[int, list[str | None]]:
    """Return {uid: [first_name|None-sentinel, username, last_name]} for every ID.

    Single owner for the batch-miss path shared by :func:`get_mention_data_batch`
    and :func:`get_first_names_batch`: the cached values are served without I/O
    (repeat IDs dropped via ``dict.fromkeys``), the remainder fetched in one
    ``IN`` query, full triples populated into the cache, and absent users
    sentineled so repeat renders skip the round-trip. Miss semantics cannot
    drift between readers when only one function implements them.
    """
    result: dict[int, list[str | None]] = {}
    missing: list[int] = []
    unique_ids = list(dict.fromkeys(user_ids))
    # * The batch readers consult both cache layers. The L1 pass is
    # * free, and the L2 pass costs one Redis round trip for the keys
    # * L1 missed, so a warm Redis serves the batch without a database
    # * query even right after a restart.
    cached = await user_mention_cache.peek_many(unique_ids)
    for uid in unique_ids:
        value = cached.get(uid, CACHE_MISS)
        if value is not CACHE_MISS:
            result[uid] = cast("list[str | None]", value)
        else:
            missing.append(uid)
    if not missing:
        return result
    # * Batch-fetch only uncached users from the database in a single query.
    # * The cache revision is captured before the read: an invalidation that
    # * lands while it runs (an erasure, a profile update) makes the rows
    # * stale, so the batch must not publish them back into L1 or Redis.
    revision = user_mention_cache.revision()
    docs = await db_call(
        lambda: fetch_all(
            select(
                telegram_users.c.user_id,
                telegram_users.c.first_name,
                telegram_users.c.username,
                telegram_users.c.last_name,
            ).where(telegram_users.c.user_id.in_(missing))
        )
    )
    publish = user_mention_cache.revision() == revision
    for doc in docs:
        uid = doc["user_id"]
        # * Populate L1 (and fire-and-forget L2 Redis write) for next lookup.
        triple = [
            doc.get("first_name") or str(uid),
            doc.get("username"),
            doc.get("last_name"),
        ]
        if publish:
            user_mention_cache.put(uid, triple)
        result[uid] = triple
    # * Fill fallback for users not found in DB either and cache the sentinel so
    # * subsequent calls skip the database round-trip on the next lookup.
    for uid in missing:
        if uid not in result:
            if publish:
                user_mention_cache.put(uid, list(_NOT_FOUND_SENTINEL))
            result[uid] = list(_NOT_FOUND_SENTINEL)
    return result


async def get_mention_data_batch(
    user_ids: list[int],
) -> dict[int, tuple[str, str | None]]:
    """Fetch (first_name, username) for multiple users, checking cache for each ID first.

    Cache-aware: IDs found in L1 are returned immediately; only uncached IDs trigger
    a batch database query.  Newly fetched data is populated into the mention cache.
    """
    triples = await _mention_triples(user_ids)
    result: dict[int, tuple[str, str | None]] = {}
    for uid, data in triples.items():
        # * data[0] may be None (not-found sentinel); fall back to str(uid).
        fname = cast("str", data[0]) if data[0] is not None else str(uid)
        result[uid] = (
            fname,
            cast("str | None", data[1] if len(data) > 1 else None),
        )
    return result


async def get_first_names_batch(user_ids: list[int]) -> dict[int, str]:
    """Fetch first names for multiple users, checking L1 first.

    IDs already in the in-memory mention cache are served without I/O; only
    uncached IDs trigger one batch database query. Users missing from the DB
    get the not-found sentinel cached so repeat renders skip the round-trip.
    Found rows populate the full mention triple (the projection covers
    first_name, username, and last_name, exactly like
    :func:`_fetch_mention_triple`), so repeat renders by any reader skip
    the round-trip without corrupting change detection.
    """
    triples = await _mention_triples(user_ids)
    return {
        uid: (cast("str", data[0]) if data[0] is not None else str(uid))
        for uid, data in triples.items()
    }


async def get_first_name(user_id: int, fallback: str = "") -> str:
    """Return the stored first_name or caller's fallback (L1 → L2 Redis → DB cached).

    Routes through ``user_mention_cache.get_or_fetch`` so all three layers are
    checked in order and both L1 and L2 are populated on a miss -- exactly the
    same path as ``get_user_mention_data``.  Calling this function never causes
    a redundant database round-trip for a user already fetched by either helper.

    When the user has no row in ``telegram_users``, ``_fetch`` stores the
    sentinel ``[None, None, None]`` in the cache.  The sentinel is distinguished from a
    real name so the caller's ``fallback`` is returned instead of a raw numeric ID
    string (e.g. ``"Admin"`` instead of ``"123456789"``).
    """

    async def _fetch() -> list[str | None]:
        return await _fetch_mention_triple(user_id)

    data = await user_mention_cache.get_or_fetch(user_id, _fetch)
    # * A bare user row with no first_name is cached as the numeric id, and a
    # * missing row as the all-None sentinel. Both are placeholders, so the
    # * caller's fallback wins; only a real stored name is returned verbatim.
    name = data[0]
    return (
        cast("str", name)
        if name is not None and not is_placeholder_name(name)
        else fallback
    )


async def total_users() -> int:
    """Get the total number of known users."""
    count = await db_call(lambda: fetch_value(_SEL_TOTAL_USERS))
    return int(count or 0)


# * Sort keys for all_users_page(). Every key maps to a column that carries
# * an index, and to the tie-break column that keeps the page order stable
# * across pages.
# * The name sorts run on the lowercase form, which is the expression the
# * name search already indexes. Sorting on the raw columns instead would
# * order the list by raw byte value, so every capitalised name would sort
# * before every lowercase one.
_USER_SORT_FIELDS: dict[str, tuple[str, int, str]] = {
    "first_name": ("first_name_lower", 1, "user_id"),
    "username": ("username_lower", 1, "user_id"),
    "user_id": ("user_id", 1, "user_id"),
    "last_updated": ("updated_at", -1, "user_id"),
}
_DEFAULT_USER_SORT: str = "first_name"


def _sort_column(field: str):
    """Return the column a sort field maps to."""
    if field == "first_name_lower":
        return func.lower(telegram_users.c.first_name)
    if field == "username_lower":
        return func.lower(telegram_users.c.username)
    return telegram_users.c[field]


async def all_users_page(
    *, skip: int = 0, limit: int = 200, sort_by: str = _DEFAULT_USER_SORT
) -> list[UserDoc]:
    """Return one page of known users (server-side skip/limit).

    Prefer this over loading every user for paginated views: only the
    visible slice travels over the wire regardless of the table size.
    """
    field, direction, tie_break = _USER_SORT_FIELDS.get(
        sort_by, _USER_SORT_FIELDS[_DEFAULT_USER_SORT]
    )
    # * Clamp once so cursor limit and fetch length can never disagree;
    # * callers always pass positive values, this only pins the edge.
    page_size = max(1, limit)
    sort_column = _sort_column(field)
    order_clauses = [sort_column.desc() if direction < 0 else sort_column.asc()]
    # * The tie-break keeps the order stable when two rows share the sort
    # * key, so a user cannot appear on two pages or on none.
    if tie_break != field:
        order_clauses.append(telegram_users.c[tie_break].asc())
    rows = await db_call(
        lambda: fetch_all(
            select(*_USER_COLUMNS)
            .order_by(*order_clauses)
            .offset(max(0, skip))
            .limit(page_size)
        )
    )
    return cast("list[UserDoc]", rows)


async def search_by_name(needle: str, limit: int = 5) -> list[UserDoc]:
    """Return up to ``limit`` known users whose name or username starts with ``needle``.

    Runs a server-side prefix query against the lowercase form of the
    searchable columns with a result cap so only matching rows (and only the
    fields needed for target resolution) travel over the wire, regardless of
    the table size.
    """
    if not needle or limit <= 0:
        return []
    # * Clamp: negative limits act as single-batch cursors in the driver and
    # * huge limits are unbounded scans; both would bypass the caps above.
    limit = max(1, min(limit, 100))
    # * The query runs against the lowercase form with a case-sensitive
    # * anchored prefix. PostgreSQL cannot serve a case-insensitive match
    # * from an index, so the lowercase expression makes the prefix a range
    # * scan instead of a full table scan on every search.
    prefix = needle.lower()
    rows = await db_call(
        lambda: fetch_all(
            select(
                telegram_users.c.user_id,
                telegram_users.c.first_name,
                telegram_users.c.username,
            )
            .where(
                or_(
                    func.lower(telegram_users.c.first_name).startswith(
                        prefix, escape="\\", autoescape=True
                    ),
                    func.lower(telegram_users.c.username).startswith(
                        prefix, escape="\\", autoescape=True
                    ),
                )
            )
            .limit(limit)
        )
    )
    return cast("list[UserDoc]", rows)


async def get_by_username(username: str) -> tuple[int, str] | None:
    """Resolve an exact username to ``(user_id, first_name)`` from the cache.

    This is a deterministic fallback for the briefcase where both live
    resolvers are unavailable: Telegram's Bot API misses some users and the
    MTProto client can be parked after a session invalidation. The member
    cache stores usernames observed on real updates and indexes their
    lowercase form, so an exact match needs no scan and cannot guess a
    different person the way a partial name search can.
    """
    needle = username.lstrip("@").strip().lower()
    if not needle:
        return None
    row = await db_call(lambda: fetch_one(_SEL_BY_USERNAME.params(needle=needle)))
    if row is None:
        return None
    uid = row["user_id"]
    if uid is None or int(uid) <= 0:
        return None
    return int(uid), str(row["first_name"] or "")


# ────────────────────────────── Writes ───────────────────────────── #


async def ensure_users(sess: AsyncSession, *user_ids: int) -> None:
    """Create the identity rows other tables reference when they are missing.

    The member cache only learns a profile from an observed Telegram
    update, so a moderator acting on an account the bot has never seen
    would otherwise fail the ``telegram_users`` foreign key and lose the
    write. The insert is idempotent and joins the caller's transaction, so
    the identity rows and the dependent write land together.
    """
    unique_ids = list(dict.fromkeys(uid for uid in user_ids if uid > 0))
    if not unique_ids:
        return
    await sess.execute(
        pg_insert(telegram_users)
        .values([{"user_id": uid} for uid in unique_ids])
        .on_conflict_do_nothing(index_elements=["user_id"])
    )


async def upsert_user(
    user_id: int,
    username: str | None,
    first_name: str,
    last_name: str | None = None,
) -> bool:
    """Update or insert a user's profile information.

    Returns True when the database accepted the write, False when the erased-
    identity guard refused it. Callers must not publish the incoming identity
    to the mention cache on a refusal: the database stayed erased and a cached
    triple would hide that fact from every later write check.

    ``username`` and ``last_name`` are treated as "unknown, preserve existing":
    when a caller passes ``None`` for either field, the previous stored value
    is left intact. This lets moderator-side flows (ban, kick, promote, /check)
    refresh the displayed name without wiping the username the user may have
    set later. Pass an explicit empty string only if you intend to clear the
    field.
    """
    now = utc_now()
    values: dict[str, object] = {
        "user_id": user_id,
        "first_name": first_name,
        "updated_at": now,
        "last_seen_at": now,
    }
    updates: dict[str, object] = {
        "first_name": first_name,
        "updated_at": now,
        "last_seen_at": now,
    }
    if username is not None:
        values["username"] = username
        updates["username"] = username
    if last_name is not None:
        values["last_name"] = last_name
        updates["last_name"] = last_name
    # * The conflict action carries only the refreshed fields, so a partial
    # * write (username or last name left as "unknown, preserve existing")
    # * keeps the stored column instead of clearing it.
    # * The first sighting is not overwritten: the conflict action leaves
    # * first_seen_at alone, so the moment the profile arrived stays readable.
    try:
        await db_call(
            lambda: run(
                pg_insert(telegram_users)
                .values(**values)
                .on_conflict_do_update(
                    index_elements=["user_id"],
                    set_=updates,
                )
            )
        )
    except asyncio.CancelledError:
        raise
    except IntegrityError as exc:
        if constraint_name(exc) != "ck_telegram_users_erased_identity":
            raise
        # * The database refused to repopulate an erased profile. Drop the
        # * stale mention entry too, so no process keeps serving the name it
        # * just tried to write back.
        user_mention_cache.invalidate(user_id)
        return False
    # * Populate the mention cache when the write carried every field, so
    # * the next change check hits L1 and an unchanged profile is not
    # * rewritten on every message. A partial write (username or last name
    # * left as "unknown, preserve existing") cannot reconstruct the stored
    # * triple, so it invalidates instead.
    if username is not None and last_name is not None:
        user_mention_cache.put(user_id, [first_name, username, last_name])
    else:
        user_mention_cache.invalidate(user_id)
    return True


async def touch_chat_member(chat_id: int, user_id: int) -> None:
    """Record that a user was seen in a group.

    The membership cache feeds the community directory and the retention
    sweep. It is written from the MTProto harvest, which already holds the
    group and the member list, and a failure is non-fatal for the harvest.

    Erasure deletes membership rows, so the guard is part of this statement:
    an `INSERT ... SELECT ... WHERE NOT EXISTS` skips erased accounts in the
    same round trip a plain insert would take. Without it the next harvest
    would recreate the row the erasure removed.
    """
    now = utc_now()
    erased = (
        select(literal(1))
        .where(
            telegram_users.c.user_id == user_id,
            telegram_users.c.erased_at.is_not(None),
        )
        .exists()
    )
    values = select(
        literal(chat_id),
        literal(user_id),
        literal("member"),
        literal(now),
        literal(now),
        literal(now),
    ).where(~erased)
    await db_call(
        lambda: run(
            pg_insert(chat_members)
            .from_select(
                [
                    "chat_id",
                    "user_id",
                    "status",
                    "joined_at",
                    "last_seen_at",
                    "updated_at",
                ],
                values,
            )
            .on_conflict_do_update(
                index_elements=["chat_id", "user_id"],
                set_={
                    "status": "member",
                    "last_seen_at": now,
                    "updated_at": now,
                },
            )
        )
    )


async def upsert_user_if_changed(
    user_id: int,
    username: str | None,
    first_name: str,
    last_name: str | None = None,
) -> bool:
    """Write user profile to DB only when identity data has changed since last cache entry.

    Checks the mention cache first.  When the cached
    (first_name, username, last_name) triple matches the incoming data, the
    DB write is skipped entirely and False is returned.  This eliminates
    the database round-trip for the vast majority of updates (where identity
    data has not changed) and makes the hot-path profile handler nearly
    free.  Legacy two-element cache entries count as changed.

    Both cache layers are consulted.  The in-memory layer is bounded and
    thrashes once the community holds more active users than it can hold,
    so an L1-only check would fall through to a database write for every
    message of every user outside the working set.

    The guard only works because :func:`upsert_user` populates the mention
    cache on a complete write; invalidating instead would leave every
    ordinary member with an empty cache entry and one write per message.

    Returns True when a DB write was performed, False when skipped.
    """
    cached = await user_mention_cache.peek(user_id)
    # * Compare the full triple: last_name-only changes must also write.
    if (
        isinstance(cached, list)
        and len(cached) == 3
        and cached[0] == first_name
        and cached[1] == username
        and cached[2] == last_name
    ):
        return False
    return await upsert_user(user_id, username, first_name, last_name)


async def refresh_display_name(user_id: int, first_name: str) -> bool:
    """Store a freshly resolved display name when it differs from the cache.

    A read-only view that resolves a name must not pay for a database
    write and a cache eviction on every lookup: the mention cache already
    holds the name the view would store, so the write only runs when the
    name actually changed. Returns True when a write was performed.

    Only the display name is refreshed. The username and the last name
    stay as they are: the caller resolved a name, not a full profile.
    """
    cached = await user_mention_cache.peek(user_id)
    triple = _cached_triple(cached) if isinstance(cached, list) else (None, None, None)
    if isinstance(cached, list) and triple[0] == first_name:
        return False
    # * The refresh owns the revision window: capture before the write so an
    # * erasure landing during it cannot be undone by the re-warm below.
    revision = user_mention_cache.revision()
    written = await upsert_user(user_id, None, first_name)
    if not written:
        # * The erased-identity guard refused the write. Re-warming here would
        # * put the harvested name back into L1 and Redis, defeating erasure.
        user_mention_cache.invalidate(user_id)
        return False
    # * A display-name-only write invalidates the entry exactly once. Any
    # * other mutation in this window, such as the erasure sweep, must win:
    # * re-warming after it would restore a cleared identity to L1 and Redis.
    if user_mention_cache.revision() != revision + 1:
        return True
    if isinstance(cached, list) and len(cached) == 3 and cached[0] is not None:
        user_mention_cache.put(user_id, [first_name, triple[1], triple[2]])
    return True


async def harvest_user_identity(
    user_id: int,
    username: str | None,
    first_name: str,
    last_name: str | None = None,
) -> bool:
    """Persist a full identity snapshot taken from a live Telegram User object.

    Unlike ``upsert_user_if_changed`` (where ``None`` means "unknown, keep
    the stored value"), ``None`` here means "absent on Telegram": fields the
    object omits are cleared via ``""`` so removals (deleted username or
    last name) propagate instead of lingering stale. Use only with data
    taken directly from a live ``User`` object, never with partial data
    from ban/promote/check-by-ID paths (those must keep ``None``).
    """
    return await upsert_user_if_changed(
        user_id,
        username if username is not None else "",
        first_name,
        last_name if last_name is not None else "",
    )


def remember_identity(
    user_id: int,
    first_name: str | None,
    username: str | None,
    last_name: str | None,
) -> None:
    """Mirror a resolved identity into L1 without touching other layers.

    Used after a Telegram-side resolve so the next read hits L1. A partial
    write through :func:`upsert_user` invalidates rather than populates, so
    without this the next read would miss L1. A fully empty identity stores
    the not-found sentinel.

    The write stays process-local on purpose. A resolve that failed for a
    transient reason (network, MTProto outage) also resolves to no
    identity, and publishing that sentinel to Redis would show the numeric
    fallback for every process until the L2 TTL. Positive identities are
    already durable in ``telegram_users``, so a neighbouring process can
    load them from the database.
    """
    if first_name is None:
        user_mention_cache.put_local(user_id, list(_NOT_FOUND_SENTINEL))
    else:
        user_mention_cache.put_local(user_id, [first_name, username, last_name])
