# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""MTProto member harvest: one-shot group backfill into the member cache."""

from __future__ import annotations

import asyncio

from tcbot.database import mtproto as _mtproto_pkg
from tcbot.utils.dispatch import gather_bounded
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
    # * The member scan itself stays sequential (Telegram order); the DB
    # * writes batch instead of awaiting one at a time.
    from tcbot.database import users_cache  # noqa: PLC0415 (avoid import cycle)

    c = _mtproto_pkg._client
    if _mtproto_pkg._auth_dead:
        raise RuntimeError("MTProto session invalidated; refusing to harvest.")
    if c is None or not c.is_connected:
        raise RuntimeError("MTProto client is not connected.")
    # * A 1000-member scan is up to 1000 sequential DB writes on the event
    # * loop; cap wall time so one backfill cannot stall moderation traffic.
    deadline = _mtproto_pkg.monotonic() + _mtproto_pkg._HARVEST_BUDGET_S
    # * Valid identities batch into bounded flushes (mirrors the connected
    # * admin harvest) so writes overlap instead of awaiting each one. The
    # * batch stays small: at most _HARVEST_BATCH pending writes at a time.
    _HARVEST_BATCH: int = 50
    pending: list = []
    count = 0

    async def _flush() -> None:
        nonlocal count
        if not pending:
            return
        results = await gather_bounded(list(pending))
        for result in results:
            if isinstance(result, BaseException):
                log.debug("Member harvest write failed: %s", result)
            else:
                count += 1
        pending.clear()

    try:
        async for member in c.get_chat_members(chat_id, limit=limit):
            if _mtproto_pkg.monotonic() >= deadline:
                await _flush()
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
            pending.append(
                users_cache.harvest_user_identity(
                    user.id,
                    getattr(user, "username", None),
                    fname,
                    getattr(user, "last_name", None),
                )
            )
            if len(pending) >= _HARVEST_BATCH:
                await _flush()
        await _flush()
        return count
    except Exception as exc:
        if getattr(exc, "value", None) is not None:  # FloodWait-likes carry .value
            log.warning("Member harvest stopped early in %d: %s", chat_id, exc)
            # * Flush what was collected before the flood so partial progress
            # * survives; the count so far is returned either way.
            try:
                await _flush()
            except asyncio.CancelledError:
                raise
            except Exception as flush_exc:
                log.debug("Member harvest partial flush failed: %s", flush_exc)
            return count
        raise
