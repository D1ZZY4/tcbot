# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""MTProto client lifecycle: lease claim, connect, heartbeat, and auth parking."""

from __future__ import annotations

import asyncio
import os
import secrets
import socket
from typing import TYPE_CHECKING

from tcbot import cfg
from tcbot.database import mtproto as _mtproto_pkg
from tcbot.utils.logger import get_logger

if TYPE_CHECKING:
    from pyrogram import Client

    from tcbot.database.mtproto_store import MongoStorage

# * Logger keeps the pre-split name so log output is unchanged.
log = get_logger("tcbot.database.mtproto")


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
    if _mtproto_pkg._client is not None:
        return _mtproto_pkg._client
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

    _mtproto_pkg._client = Client(
        cfg.mtproto_session,
        api_id=cfg.api_id,
        api_hash=cfg.api_hash,
        bot_token=cfg.bot_token,
        storage_engine=MongoStorage(cfg.mtproto_session),
    )
    return _mtproto_pkg._client


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
    if _mtproto_pkg._auth_dead:
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
        claimed = await store.claim_owner(owner, ttl_s=_mtproto_pkg._LEASE_TTL_S)
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
    _mtproto_pkg._lease_owner = owner
    try:
        async with asyncio.timeout(_mtproto_pkg._START_TIMEOUT_S):
            await c.start()
    except TimeoutError as exc:
        await _release_lease_quietly(store, owner)
        _mtproto_pkg._lease_owner = None
        raise RuntimeError(
            f"MTProto bot session timed out after {_mtproto_pkg._START_TIMEOUT_S:.0f}s."
        ) from exc
    except asyncio.CancelledError:
        await _release_lease_quietly(store, owner)
        _mtproto_pkg._lease_owner = None
        raise
    except Exception as exc:
        # * A rejected stored key (duplicate live instance, or a
        # * server-invalidated key) must degrade, never abort boot: killing
        # * the whole process over MTProto takes federation enforcement
        # * offline for a lookup enhancement. Park it sticky (no in-process
        # * re-login races) and serve Bot-API-only until a restart.
        if is_auth_key_duplicated(exc):
            _mtproto_pkg._auth_dead = True
            await _release_lease_quietly(store, owner)
            _mtproto_pkg._lease_owner = None
            log.exception(
                "MTProto connect rejected (406 AUTH_KEY_DUPLICATED): another "
                "instance shares this session or the key is dead. Serving "
                "Bot-API-only. Operator action: stop every bot instance, "
                "delete the '%s:*' docs from mtproto_state, then boot one.",
                cfg.mtproto_session,
            )
            return False
        await _release_lease_quietly(store, owner)
        _mtproto_pkg._lease_owner = None
        raise RuntimeError(f"MTProto bot session failed: {exc}") from exc
    log.info("MTProto connected (bot session).")
    _mtproto_pkg._heartbeat_task = asyncio.get_running_loop().create_task(
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
    try:
        while True:
            await asyncio.sleep(_mtproto_pkg._HEARTBEAT_S)
            try:
                held = await store.refresh_owner(owner, ttl_s=_mtproto_pkg._LEASE_TTL_S)
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
            if _mtproto_pkg._client is c:
                _mtproto_pkg._client = None
            return
    except asyncio.CancelledError:
        raise


async def stop() -> None:
    """Disconnect the shared client and release the owner lease.

    Best-effort, never raises (except CancelledError which propagates).
    """
    task, _mtproto_pkg._heartbeat_task = _mtproto_pkg._heartbeat_task, None
    if task is not None and not task.done():
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    owner = _mtproto_pkg._lease_owner
    _mtproto_pkg._lease_owner = None
    if owner is not None:
        try:
            from tcbot.database.mtproto_store import (  # noqa: PLC0415 (same as client())
                MongoStorage,
            )
        except ImportError:
            pass
        else:
            await _release_lease_quietly(MongoStorage(cfg.mtproto_session), owner)
    c, _mtproto_pkg._client = _mtproto_pkg._client, None
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
    return _mtproto_pkg._auth_dead


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
    if _mtproto_pkg._auth_dead:
        return
    _mtproto_pkg._auth_dead = True
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
