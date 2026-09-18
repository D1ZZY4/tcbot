# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""MTProto client: bot-token session for lookups beyond Bot API enumeration."""

from __future__ import annotations

import asyncio
import os
import secrets
import socket
from typing import TYPE_CHECKING

from tcbot import cfg
from tcbot.utils.logger import get_logger
from tcbot.utils.time_and_date import TELEGRAM_LOOKUP_TIMEOUT, monotonic

if TYPE_CHECKING:
    from pyrogram import Client
    from pyrogram.types import User

    from tcbot.database.mtproto_store import MongoStorage

log = get_logger(__name__)

_client: Client | None = None
_lease_owner: str | None = None
_heartbeat_task: asyncio.Task[None] | None = None
_auth_dead: bool = False

# * Ceiling for the initial session connect at boot. A network partition
# * must fail the boot loudly instead of hanging it forever.
_START_TIMEOUT_S: float = 60.0

# * Single-owner lease bounds: only the instance holding the lease keeps a
# * live MTProto connection, because Telegram kills the shared auth key
# * when two clients connect with it at once (406 AUTH_KEY_DUPLICATED).
# * The heartbeat refreshes well inside the TTL; a crashed holder fails
# * over to the next claimant after at most one TTL.
_LEASE_TTL_S: float = 90.0
_HEARTBEAT_S: float = 30.0

# * Wall-clock cap for one harvest_group_members scan: the loop is up to
# * ``limit`` sequential DB writes on the event loop, so an unbounded scan
# * of a mega-group would stall moderation traffic behind a backfill.
_HARVEST_BUDGET_S: float = 25.0


def _instance_id() -> str:
    """Owner label for lease diagnostics (host:pid:random, no secrets)."""
    return f"{socket.gethostname()}:{os.getpid()}:{secrets.token_hex(4)}"


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
    """Claim the single-owner lease, then connect the shared client.

    Returns True when the client connected, False when another live
    instance holds the lease, the claim failed, or Telegram rejects the
    stored key as duplicated/invalidated (Bot-API-only degraded mode:
    every resolver returns None exactly like the serverless path, and
    moderation is unaffected). A degraded False is NOT an error: aborting
    boot over MTProto would take federation enforcement offline for a
    lookup enhancement, which is the worse trade.

    Raises RuntimeError when unusable (unconfigured or a genuinely failed
    login): those are always real and boot must fail loudly instead of
    serving a silently downgraded bot.
    """
    global _heartbeat_task, _lease_owner, _auth_dead
    if _auth_dead:
        raise RuntimeError(
            "MTProto session was invalidated (AUTH_KEY_DUPLICATED); refusing "
            "to reconnect in-process. Stop every instance, purge the session "
            "docs, and boot one."
        )
    c = client()
    if c.is_connected:
        return True
    from tcbot.database.mtproto_store import (  # noqa: PLC0415 (same as client())
        MongoStorage,
    )

    owner = _instance_id()
    store = MongoStorage(cfg.mtproto_session)
    try:
        claimed = await store.claim_owner(owner, ttl_s=_LEASE_TTL_S)
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception(
            "MTProto owner-lease claim failed; starting degraded without MTProto"
        )
        return False
    if not claimed:
        log.warning(
            "MTProto owner lease held by another live instance; running "
            "Bot-API-only. Stop the duplicate instance if this one should "
            "own the session."
        )
        return False
    _lease_owner = owner
    try:
        async with asyncio.timeout(_START_TIMEOUT_S):
            await c.start()
    except TimeoutError as exc:
        await _release_lease_quietly(store, owner)
        _lease_owner = None
        raise RuntimeError(
            f"MTProto bot session timed out after {_START_TIMEOUT_S:.0f}s."
        ) from exc
    except asyncio.CancelledError:
        await _release_lease_quietly(store, owner)
        _lease_owner = None
        raise
    except Exception as exc:
        # * A rejected stored key (duplicate live instance, or a
        # * server-invalidated key) must degrade, never abort boot: killing
        # * the whole process over MTProto takes federation enforcement
        # * offline for a lookup enhancement. Park it sticky (no in-process
        # * re-login races) and serve Bot-API-only until a restart.
        if is_auth_key_duplicated(exc):
            _auth_dead = True
            await _release_lease_quietly(store, owner)
            _lease_owner = None
            log.exception(
                "MTProto connect rejected (406 AUTH_KEY_DUPLICATED): another "
                "instance shares this session or the key is dead. Serving "
                "Bot-API-only. Operator action: stop every bot instance, "
                "delete the '%s:*' docs from mtproto_state, then boot one.",
                cfg.mtproto_session,
            )
            return False
        await _release_lease_quietly(store, owner)
        _lease_owner = None
        raise RuntimeError(f"MTProto bot session failed: {exc}") from exc
    log.info("MTProto connected (bot session).")
    _heartbeat_task = asyncio.get_running_loop().create_task(
        _heartbeat_lease(c, store, owner)
    )
    return True


async def _release_lease_quietly(store: MongoStorage, owner: str) -> None:
    """Release the owner lease; expiry covers leftovers, never raises."""
    try:
        await store.release_owner(owner)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        log.debug("MTProto lease release failed (expiry covers it): %s", exc)


async def _heartbeat_lease(c: Client, store: MongoStorage, owner: str) -> None:
    """Renew the owner lease until cancelled; park the client when fenced out.

    Owned by start()/stop(): stop() cancels this task on shutdown. A lost
    lease means another instance took over after our heartbeat stalled past
    expiry, so the client stops instead of sharing one auth key twice.
    """
    global _client
    try:
        while True:
            await asyncio.sleep(_HEARTBEAT_S)
            try:
                held = await store.refresh_owner(owner, ttl_s=_LEASE_TTL_S)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("MTProto lease heartbeat failed; retrying next beat")
                continue
            if held:
                continue
            log.error(
                "MTProto owner lease lost; stopping the client to avoid "
                "duplicate session use. Identity lookups degrade to Bot-API-only."
            )
            try:
                await c.stop()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.debug("MTProto fenced-stop failed (non-fatal): %s", exc)
            if _client is c:
                _client = None
            return
    except asyncio.CancelledError:
        raise


async def stop() -> None:
    """Disconnect the shared client and release the owner lease.

    Best-effort, never raises (except CancelledError which propagates).
    """
    global _client, _heartbeat_task, _lease_owner
    task, _heartbeat_task = _heartbeat_task, None
    if task is not None and not task.done():
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    owner = _lease_owner
    _lease_owner = None
    if owner is not None:
        try:
            from tcbot.database.mtproto_store import (  # noqa: PLC0415 (same as client())
                MongoStorage,
            )
        except ImportError:
            pass
        else:
            await _release_lease_quietly(MongoStorage(cfg.mtproto_session), owner)
    c, _client = _client, None
    if c is None:
        return
    try:
        await c.stop()
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        log.debug("MTProto stop failed (non-fatal): %s", exc)


def is_auth_dead() -> bool:
    """Report whether Telegram invalidated the shared auth key (see handle_auth_failure)."""
    return _auth_dead


def is_auth_key_duplicated(exc: BaseException) -> bool:
    """Check whether *exc* is Telegram's 406 AUTH_KEY_DUPLICATED."""
    try:
        from pyrogram.errors import (  # noqa: PLC0415 (heavy extra; import only on use)
            AuthKeyDuplicated,
        )
    except ImportError:
        return type(exc).__name__ == "AuthKeyDuplicated"
    return isinstance(exc, AuthKeyDuplicated)


async def handle_auth_failure() -> None:
    """Park MTProto after Telegram invalidates the shared auth key.

    Idempotent and never raises: stops the client, releases the lease, and
    marks the session dead so every resolver degrades to Bot-API-only
    instead of hammering a dead key. Recovery is operator-driven by design
    (an in-process re-login would race a still-live duplicate): stop ALL
    instances, purge the `<session>:*` docs from `mtproto_state`, then boot
    exactly one instance and the bot-token login mints a fresh key.
    """
    global _auth_dead
    if _auth_dead:
        return
    _auth_dead = True
    log.error(
        "MTProto auth key invalidated by Telegram (406 AUTH_KEY_DUPLICATED): "
        "another instance shares this session. Parked MTProto; identity "
        "lookups degrade to Bot-API-only. Operator action: stop every bot "
        "instance, delete the '%s:*' docs from mtproto_state, then boot one.",
        cfg.mtproto_session,
    )
    try:
        await stop()
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        log.debug("MTProto park-teardown failed (non-fatal): %s", exc)


async def _fetch_user(target_id: int) -> User | None:
    """Single peer lookup shared by resolve_user and is_bot_user.

    Returns the raw peer, or None when the client is down, the lookup
    times out, or the peer is unknown/rate-limited. Cancellation propagates.
    """
    c = _client
    if _auth_dead or c is None or not c.is_connected:
        return None
    try:
        async with asyncio.timeout(TELEGRAM_LOOKUP_TIMEOUT):
            return await c.get_users(target_id)
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


async def resolve_user(target_id: int) -> tuple[str, str | None, str | None] | None:
    """Resolve (first_name, username, last_name) for a user ID via MTProto.

    Returns None when the client is not running (serverless paths), when it
    drops mid-run, or when the peer is unknown, rate-limited, or nameless:
    every case just means "fall through to the next resolution source".
    Cancellation always propagates.
    """
    user = await _fetch_user(target_id)
    if user is None:
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
    if _auth_dead or c is None or not c.is_connected:
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


async def is_bot_user(target_id: int) -> bool | None:
    """Return is_bot for a user ID via MTProto, or None when unknowable.

    Uses the same peer lookup as resolve_user but surfaces the bot flag
    instead of the name triple. Promotion and transfer guards use it to
    refuse bot targets; client down, unknown peer, flood, and nameless
    all map to None (unknown, never False-as-fact).
    """
    user = await _fetch_user(target_id)
    if user is None:
        return None
    return bool(getattr(user, "is_bot", False))


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

    c = _client
    if _auth_dead:
        raise RuntimeError("MTProto session invalidated; refusing to harvest.")
    if c is None or not c.is_connected:
        raise RuntimeError("MTProto client is not connected.")
    count = 0
    # * A 1000-member scan is up to 1000 sequential DB writes on the event
    # * loop; cap wall time so one backfill cannot stall moderation traffic.
    deadline = monotonic() + _HARVEST_BUDGET_S
    try:
        async for member in c.get_chat_members(chat_id, limit=limit):
            if monotonic() >= deadline:
                log.warning(
                    "Member harvest stopped on timeslice in %d (%ds budget).",
                    chat_id,
                    int(_HARVEST_BUDGET_S),
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
