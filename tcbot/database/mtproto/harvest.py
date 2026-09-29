# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""MTProto member harvest: one-shot group backfill into the member cache."""

from __future__ import annotations

from tcbot.database import mtproto as _mtproto_pkg
from tcbot.utils.logger import get_logger

# * Logger keeps the pre-split name so log output is unchanged.
log = get_logger("tcbot.database.mtproto")


async def harvest_group_members(chat_id: int, *, limit: int = 1000) -> int:
    """Cache every member of *chat_id* the session can see; return harvested count.

    One-shot backfill for silent members no Bot API call ever observed: each
    seen identity lands in member_cache, so later bans and checks resolve by
    name. Stops early on FloodWait or when the timeslice budget runs out
    (returns the count so far); peer hashes persist in shared storage as a
    side effect for future direct resolves.
    """
    # * Sequential scan, no parallelism; shard per-group or page with
    # * smaller limits if a mega-group harvest ever gets too slow.
    from tcbot.database import users_cache  # noqa: PLC0415 (avoid import cycle)

    c = _mtproto_pkg._client
    if _mtproto_pkg._auth_dead:
        raise RuntimeError("MTProto session invalidated; refusing to harvest.")
    if c is None or not c.is_connected:
        raise RuntimeError("MTProto client is not connected.")
    count = 0
    # * A 1000-member scan is up to 1000 sequential DB writes on the event
    # * loop; cap wall time so one backfill cannot stall moderation traffic.
    deadline = _mtproto_pkg.monotonic() + _mtproto_pkg._HARVEST_BUDGET_S
    try:
        async for member in c.get_chat_members(chat_id, limit=limit):
            if _mtproto_pkg.monotonic() >= deadline:
                log.warning(
                    "Member harvest stopped on timeslice in %d (%ds budget).",
                    chat_id,
                    int(_mtproto_pkg._HARVEST_BUDGET_S),
                )
                return count
            user = getattr(member, "user", None)
            fname = getattr(user, "first_name", None) if user is not None else None
            if user is None or getattr(user, "is_bot", False) or not fname:
                continue
            try:
                await users_cache.harvest_user_identity(
                    user.id,
                    getattr(user, "username", None),
                    fname,
                    getattr(user, "last_name", None),
                )
            except Exception as exc:
                log.debug("Member harvest write failed for %d: %s", user.id, exc)
                continue
            count += 1
    except Exception as exc:
        if getattr(exc, "value", None) is not None:  # FloodWait-likes carry .value
            log.warning("Member harvest stopped early in %d: %s", chat_id, exc)
            return count
        raise
    return count
