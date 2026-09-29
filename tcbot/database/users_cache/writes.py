# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Member profile cache: upserts, harvest writes, and L1 mirroring."""

from __future__ import annotations

from tcbot.database.cache import user_mention_cache
from tcbot.database.mongos import db_call
from tcbot.utils.time_and_date import utc_now

from .reads import _NOT_FOUND_SENTINEL, _cached_triple, _members


async def upsert_user(
    user_id: int,
    username: str | None,
    first_name: str,
    last_name: str | None = None,
) -> None:
    """Update or insert a user's profile information into the cache.

    ``username`` and ``last_name`` are treated as "unknown, preserve existing":
    when a caller passes ``None`` for either field, the previous stored value
    is left intact. This lets moderator-side flows (ban, kick, promote, /check)
    refresh the displayed name without wiping the username the user may have
    set later. Pass an explicit empty string only if you intend to clear the
    field.
    """
    now = utc_now()
    update: dict[str, object] = {
        "user_id": user_id,
        "first_name": first_name,
        "last_updated": now,
    }
    if username is not None:
        update["username"] = username
    if last_name is not None:
        update["last_name"] = last_name
    await db_call(
        _members().update_one(
            {"user_id": user_id},
            {
                "$set": update,
                "$setOnInsert": {
                    "commit_date": now,
                },
            },
            upsert=True,
        )
    )
    # * Invalidate mention cache so the next read reflects the updated profile.
    user_mention_cache.invalidate(user_id)


async def upsert_user_if_changed(
    user_id: int,
    username: str | None,
    first_name: str,
    last_name: str | None = None,
) -> bool:
    """Write user profile to DB only when identity data has changed since last cache entry.

    Checks the L1 in-memory mention cache first.  When the cached
    (first_name, username, last_name) triple matches the incoming data, the
    DB write is skipped entirely and False is returned.  This eliminates
    the MongoDB round-trip for the vast majority of updates (where identity
    data has not changed) and makes the hot-path member-cache handler
    nearly free.  Legacy two-element cache entries count as changed.

    Returns True when a DB write was performed, False when skipped.
    """
    cached = user_mention_cache.get(user_id)
    # * Compare the full triple: last_name-only changes must also write.
    if isinstance(cached, list) and _cached_triple(cached) == (
        first_name,
        username,
        last_name,
    ):
        return False
    await upsert_user(user_id, username, first_name, last_name)
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
    """Mirror a resolved identity into L1 without touching the database.

    Used after a Telegram-side resolve: ``upsert_user`` invalidates rather
    than populates, so without this the next read would miss L1. A fully
    empty identity stores the not-found sentinel.
    """
    if first_name is None:
        user_mention_cache.put(user_id, list(_NOT_FOUND_SENTINEL))
    else:
        user_mention_cache.put(user_id, [first_name, username, last_name])
