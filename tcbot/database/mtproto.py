# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""MTProto client: bot-token session for lookups beyond Bot API enumeration.

The Bot API can only fetch members it already knows one by one; the
bot-token MTProto session additionally enumerates group membership, fully
automatically (no phone, no code, no prompt ever: ``sign_in_bot`` cannot
interactively block). The session lives in MongoDB (``mtproto_store``), so
every instance shares it. API_ID and API_HASH are mandatory: the bot refuses
to boot unless the session connects. Only transient runtime failures
(disconnects, unknown peers, flood waits) degrade to None so moderation
never blocks on MTProto.

Serverless paths never start the client: resolve_user() simply returns None
there.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from tcbot import cfg
from tcbot.utils.time_and_date import TELEGRAM_LOOKUP_TIMEOUT

if TYPE_CHECKING:
    from pyrogram import Client

log = logging.getLogger(__name__)

_client: Client | None = None


def is_configured() -> bool:
    """Return True when API_ID + API_HASH are set."""
    return cfg.mtproto_enabled


def client() -> Client:
    """Return the shared unstarted bot-token client.

    Raises RuntimeError when API_ID/API_HASH are not set: MTProto is
    mandatory, so a missing configuration must fail fast, never silently
    degrade into Bot-API-only mode.
    """
    global _client
    if _client is not None:
        return _client
    if not cfg.mtproto_enabled:
        raise RuntimeError(
            "API_ID/API_HASH are required for MTProto identity resolution; refusing to boot degraded."
        )
    from pyrogram import (  # noqa: PLC0415 (heavy extra; import only when configured)
        Client,
    )

    from tcbot.database.mtproto_store import (  # noqa: PLC0415 (same; keeps startup lean)
        MongoStorage,
    )

    _client = Client(
        cfg.mtproto_session,
        api_id=cfg.api_id,
        api_hash=cfg.api_hash,
        bot_token=cfg.bot_token,
        storage_engine=MongoStorage(cfg.mtproto_session),
    )
    return _client


async def start() -> bool:
    """Connect the shared client; raise RuntimeError when unusable.

    Bot-token login cannot prompt, so a failure here is always real
    (network down, revoked token, unreadable store) and boot must fail
    loudly instead of serving a silently downgraded bot.
    """
    c = client()
    if c.is_connected:
        return True
    try:
        await c.start()
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        raise RuntimeError(f"MTProto bot session failed: {exc}") from exc
    log.info("MTProto connected (bot session).")
    return True


async def stop() -> None:
    """Disconnect the shared client; best-effort, never raises."""
    global _client
    c, _client = _client, None
    if c is None:
        return
    try:
        await c.stop()
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        log.debug("MTProto stop failed (non-fatal): %s", exc)


async def resolve_user(target_id: int) -> tuple[str, str | None, str | None] | None:
    """Resolve (first_name, username, last_name) for a user ID via MTProto.

    Returns None when the client is not running (serverless paths), when it
    drops mid-run, or when the peer is unknown, rate-limited, or nameless:
    every case just means "fall through to the next resolution source".
    Cancellation always propagates.
    """
    c = _client
    if c is None or not c.is_connected:
        return None
    try:
        async with asyncio.timeout(TELEGRAM_LOOKUP_TIMEOUT):
            user = await c.get_users(target_id)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        # * FloodWait carries the wait in .value; either way the answer is
        # * "not now": never sleep the moderation loop for it.
        wait = getattr(exc, "value", None)
        if wait is not None:
            log.warning("MTProto FloodWait for %d: retry in %ss.", target_id, wait)
        else:
            log.debug("MTProto resolve failed for %d: %s", target_id, exc)
        return None
    fname: str = getattr(user, "first_name", "") or ""
    if not fname:
        return None
    return fname, getattr(user, "username", None), getattr(user, "last_name", None)


async def resolve_username(username: str) -> tuple[int, str, str | None] | None:
    """Resolve an @username to (user_id, first_name, username) via MTProto.

    Catches what Bot API username lookups miss (proven live: a username
    ``get_chat`` rejected resolved here). Exact match only, so moderation
    paths can trust it like any verified @username. Returns None when the
    client is down or the username is unknown/taken-down. Resolved peers
    stay in shared storage for later direct ID lookups.
    """
    c = _client
    if c is None or not c.is_connected:
        return None
    try:
        from pyrogram import raw  # noqa: PLC0415 (heavy extra; import only on use)

        async with asyncio.timeout(TELEGRAM_LOOKUP_TIMEOUT):
            resolved = await c.invoke(
                raw.functions.contacts.ResolveUsername(username=username.lstrip("@"))  # type: ignore[attr-defined]
            )
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        log.debug("MTProto username resolve failed for %s: %s", username, exc)
        return None
    for user in resolved.users:
        fname: str = getattr(user, "first_name", "") or ""
        if fname:
            return user.id, fname, getattr(user, "username", None)
    return None


async def harvest_group_members(chat_id: int, *, limit: int = 1000) -> int:
    """Cache every member of *chat_id* the session can see; return harvested count.

    One-shot backfill for silent members no Bot API call ever observed: each
    seen identity lands in member_cache, so later bans and checks resolve by
    name. Stops early on FloodWait (returns the count so far); peer hashes
    persist in shared storage as a side effect for future direct resolves.
    """
    # ponytail: single sequential scan, no parallelism; shard per-group or
    # page with smaller limits if a mega-group harvest ever too slow.
    from tcbot.database import users_cache  # noqa: PLC0415 (avoid import cycle)

    c = _client
    if c is None or not c.is_connected:
        raise RuntimeError("MTProto client is not connected.")
    count = 0
    try:
        async for member in c.get_chat_members(chat_id, limit=limit):
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
