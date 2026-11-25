# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""MTProto client: bot-token session for lookups beyond Bot API enumeration."""

from __future__ import annotations

import asyncio
import inspect
import os
import secrets
import socket
from dataclasses import dataclass
from typing import TYPE_CHECKING

import msgspec
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from tcbot import cfg
from tcbot.database.base import mtproto_state
from tcbot.database.engine import db_call, fetch_one, run
from tcbot.utils.circuit_breaker import CircuitOpenError
from tcbot.utils.dispatch import gather_bounded
from tcbot.utils.logger import get_logger
from tcbot.utils.time_and_date import monotonic, utc_now
from tcbot.utils.transport import TELEGRAM_LOOKUP_TIMEOUT

if TYPE_CHECKING:
    from pyrogram import Client
    from pyrogram.types import User

    from tcbot.database.mtproto_store import PostgresStorage

log = get_logger(__name__)

# ─────────── Shared mutable state (single owner: this module) ────── #

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
# * A single missed beat is an ordinary transient outage and must not drop
# * a healthy session. Two consecutive misses span one full TTL from the
# * last successful refresh, so a peer could claim the lease at any moment;
# * park our client while there is still a heartbeat of margin left.
_LEASE_MAX_MISSED_BEATS: int = 2

# * Wall-clock cap for one harvest_group_members scan: the loop is up to
# * ``limit`` sequential DB writes on the event loop, so an unbounded scan
# * of a mega-group would stall moderation traffic behind a backfill.
_HARVEST_BUDGET_S: float = 25.0

# ───────────────────────── Lifecycle ───────────────────────────── #


def _instance_id() -> str:
    """Owner label for lease diagnostics (host:pid:random, no secrets)."""
    return f"{socket.gethostname()}:{os.getpid()}:{secrets.token_hex(4)}"


def _worker_count() -> int:
    """Size the dispatcher without outgrowing the app or the database pool.

    Kurigram's default is 8 workers on a small host. More workers help when
    many independent chats are active, but every worker can hold a handler
    and a database connection. The application caps handler concurrency at
    64, so a larger count only adds idle tasks and threads.
    """
    if cfg.kurigram_workers:
        return cfg.kurigram_workers
    cpus = os.cpu_count() or 2
    pool = cfg.db_pool_size + cfg.db_max_overflow
    return max(8, min(64, cpus * 4, pool * 4))


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
        PostgresStorage,
    )

    _client = Client(
        cfg.mtproto_session,
        api_id=cfg.api_id,
        api_hash=cfg.api_hash,
        bot_token=cfg.bot_token,
        storage_engine=PostgresStorage(cfg.mtproto_session),
        workers=_worker_count(),
    )
    return _client


async def start() -> bool:
    """Claim the single-owner lease, then connect the shared client.

    Returns True when the client connected, and False only when another
    live instance holds the lease. Kurigram is the sole transport, so a
    missing session is fatal rather than a silent degrade.

    A revoked session or a missing auth key is recoverable from the bot
    token: the stale session rows are cleared under the lease and one fresh
    login is attempted. A duplicated key is not recoverable because it
    means another instance is live; it fails closed. Bad credentials and
    a failed recovery also fail closed with RuntimeError.
    """
    global _lease_owner, _heartbeat_task, _auth_dead, _client
    if _auth_dead:
        raise RuntimeError(
            "MTProto session was invalidated (AUTH_KEY_DUPLICATED, "
            "AUTH_KEY_NOT_FOUND, or SESSION_REVOKED); refusing to reconnect "
            "in-process. Stop every instance, purge the session docs, and "
            "boot one."
        )
    c = client()
    if c.is_connected:
        return True
    from tcbot.database.mtproto_store import (  # noqa: PLC0415 (same as client())
        PostgresStorage,
    )

    owner = _instance_id()
    store = PostgresStorage(cfg.mtproto_session)
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
        if is_session_revoked(exc) or is_auth_key_not_found(exc):
            # * Telegram rejected the stored key but the bot token can mint
            # * a new one. Clear only session rows under the held lease, then
            # * retry once on the same Client object, which start() resets to
            # * disconnected after a failed login.
            try:
                await store.clear_session_for_relogin()
                if not await store.refresh_owner(owner, ttl_s=_LEASE_TTL_S):
                    raise RuntimeError("MTProto lease was lost during session recovery")
                async with asyncio.timeout(_START_TIMEOUT_S):
                    await c.start()
            except asyncio.CancelledError:
                await _release_lease_quietly(store, owner)
                _lease_owner = None
                raise
            except Exception as recover_exc:
                _auth_dead = True
                await _release_lease_quietly(store, owner)
                _lease_owner = None
                raise RuntimeError(
                    f"MTProto session recovery failed: {recover_exc}"
                ) from recover_exc
            log.warning(
                "MTProto stored session was rejected by Telegram; rebuilt a "
                "fresh bot-token session."
            )
        elif _is_auth_fatal(exc):
            # * AUTH_KEY_DUPLICATED means a peer is already live. Recovering
            # * here would create two sessions and get both killed.
            _auth_dead = True
            await _release_lease_quietly(store, owner)
            _lease_owner = None
            raise RuntimeError(
                "MTProto session is held by another live instance "
                "(AUTH_KEY_DUPLICATED); stop it before starting this one."
            ) from exc
        else:
            await _release_lease_quietly(store, owner)
            _lease_owner = None
            raise RuntimeError(f"MTProto bot session failed: {exc}") from exc
    log.info("MTProto connected (bot session).")
    _heartbeat_task = asyncio.get_running_loop().create_task(
        _heartbeat_lease(c, store, owner)
    )
    return True


async def _release_lease_quietly(store: PostgresStorage, owner: str) -> None:
    """Release the owner lease; expiry covers leftovers, never raises."""
    try:
        await store.release_owner(owner)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        log.debug("MTProto lease release failed (expiry covers it): %s", exc)


async def _fence_leased_client(c: Client) -> None:
    """Stop a client whose lease can no longer be proven and clear its owner.

    A peer may claim an expired lease and connect with the same auth key,
    which Telegram rejects with AUTH_KEY_DUPLICATED. Clearing the module
    client makes is_available() false before that can happen.
    """
    global _client, _lease_owner
    try:
        await c.stop()
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        log.debug("MTProto fenced-stop failed (non-fatal): %s", exc)
    if _client is c:
        _client = None
    _lease_owner = None


async def _heartbeat_lease(c: Client, store: PostgresStorage, owner: str) -> None:
    """Renew the owner lease until cancelled; park the client when fenced out.

    Owned by start()/stop(): stop() cancels this task on shutdown. A lost
    lease means another instance took over after our heartbeat stalled past
    expiry, so the client stops instead of sharing one auth key twice.

    A failed refresh is not proof of a takeover, but a database partition
    that outlasts the lease is indistinguishable from one from this process.
    After the configured number of consecutive failed beats the client is
    parked while the lease still has a heartbeat of margin left.
    """
    missed = 0
    try:
        while True:
            await asyncio.sleep(_HEARTBEAT_S)
            try:
                held = await store.refresh_owner(owner, ttl_s=_LEASE_TTL_S)
            except asyncio.CancelledError:
                raise
            except CircuitOpenError as exc:
                # * Expected outage shape: keep the error-level shipper
                # * quiet by logging at warning without a traceback.
                log.warning("MTProto lease heartbeat deferred: %s", exc)
                held = None
            except Exception:
                log.exception("MTProto lease heartbeat failed; retrying next beat")
                held = None
            if held is True:
                missed = 0
                continue
            if held is False:
                log.error(
                    "MTProto owner lease lost; stopping the client to avoid "
                    "duplicate session use. Identity lookups degrade to Bot-API-only."
                )
                await _fence_leased_client(c)
                return
            missed += 1
            if missed >= _LEASE_MAX_MISSED_BEATS:
                log.error(
                    "MTProto lease refresh failed for %d consecutive beats; "
                    "parking the client before a peer can claim the lease.",
                    missed,
                )
                await _fence_leased_client(c)
                return
    except asyncio.CancelledError:
        raise


async def stop() -> None:
    """Disconnect the shared client and release the owner lease.

    Best-effort, never raises (except CancelledError which propagates).
    """
    global _heartbeat_task, _lease_owner, _client
    task, _heartbeat_task = _heartbeat_task, None
    if task is not None and not task.done():
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    # ! CRITICAL: Disconnect before releasing the lease. A free lease with a
    # ! still-connected client lets a rolling-restart peer claim it and reuse
    # ! the shared auth key, which Telegram rejects as AUTH_KEY_DUPLICATED.
    c = _client
    try:
        if c is not None:
            try:
                await c.stop()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.debug("MTProto stop failed (non-fatal): %s", exc)
            finally:
                _client = None
    finally:
        # * Keep the owner id until the release is attempted. Clearing it
        # * before the await used to strand the lease for its whole TTL when
        # * a second cancellation interrupted shutdown.
        owner = _lease_owner
        if owner is not None:
            try:
                from tcbot.database.mtproto_store import (  # noqa: PLC0415 (same as client())
                    PostgresStorage,
                )
            except ImportError:
                pass
            else:
                await _release_lease_quietly(
                    PostgresStorage(cfg.mtproto_session), owner
                )
            finally:
                _lease_owner = None


def is_auth_dead() -> bool:
    """Report whether Telegram invalidated the shared auth key (see handle_auth_failure)."""
    return _auth_dead


def is_available() -> bool:
    """Report whether MTProto can currently answer identity lookups.

    False when the session was parked, the client was never started, or it
    dropped. Target resolvers use this to decide whether a cached username
    is an acceptable last resort: while a live resolver exists, an unknown
    username really is unknown and must not be guessed from the cache.
    """
    c: Client | None = _client
    return not _auth_dead and c is not None and bool(c.is_connected)


def is_auth_key_duplicated(exc: BaseException) -> bool:
    """Check whether *exc* is Telegram's 406 AUTH_KEY_DUPLICATED."""
    from tcbot.modules.helper.pipelines.errors.exceptions import (  # noqa: PLC0415
        is_auth_key_duplicated as _is_auth_key_duplicated,
    )

    return _is_auth_key_duplicated(exc)


def is_auth_key_not_found(exc: BaseException) -> bool:
    """Check whether *exc* is Telegram's transport 404 AUTH_KEY_NOT_FOUND.

    Kurigram raises this from the session receive worker when the server
    reports the auth key is gone. It is a ``TransportError`` subclass, not
    an ``RPCError``, so it is detected in its own module instead.
    """
    from tcbot.modules.helper.pipelines.errors.exceptions import (  # noqa: PLC0415
        is_auth_key_not_found as _is_auth_key_not_found,
    )

    return _is_auth_key_not_found(exc)


def is_session_revoked(exc: BaseException) -> bool:
    """Check whether Telegram revoked the stored session (401 SESSION_REVOKED).

    A revoked session is not a transport failure: the auth key is still
    present locally but Telegram no longer accepts it, because the session
    was terminated from another client. Startup clears the stale session
    and performs one fresh bot-token login; a late runtime failure parks
    the client instead of reconnecting inside a live handler.
    """
    from tcbot.modules.helper.pipelines.errors.exceptions import (  # noqa: PLC0415
        is_session_revoked as _is_session_revoked,
    )

    return _is_session_revoked(exc)


def _is_auth_fatal(exc: BaseException) -> bool:
    """Return True when *exc* means the stored session can never reconnect."""
    return (
        is_auth_key_duplicated(exc)
        or is_auth_key_not_found(exc)
        or is_session_revoked(exc)
    )


async def _park_on_auth_failure(exc: BaseException) -> None:
    """Park MTProto when a lookup reports an invalidated session.

    Runtime lookups swallow their errors and fall through to the next
    resolver, which would keep a revoked session in place and log a debug
    line per lookup. The first fatal error parks the client instead, so the
    log carries one actionable line and every later lookup returns quickly.
    """
    if _auth_dead or not _is_auth_fatal(exc):
        return
    await handle_auth_failure()


async def handle_auth_failure() -> None:
    """Park MTProto after Telegram invalidates the shared auth key.

    Idempotent and never raises: stops the client, releases the lease, and
    marks the session dead so every resolver stops hammering a dead key.
    Startup handles session recovery once under the lease; a failure while
    the process is live is reported to the operator and needs a restart
    rather than an in-process re-login that could race a live duplicate.
    """
    global _auth_dead
    if _auth_dead:
        return
    _auth_dead = True
    log.error(
        "MTProto session invalidated by Telegram (406 AUTH_KEY_DUPLICATED, "
        "transport 404 AUTH_KEY_NOT_FOUND, or 401 SESSION_REVOKED): the "
        "stored session is dead. Parked MTProto; identity lookups degrade to "
        "Bot-API-only. Operator action: stop every bot instance, delete the "
        "'%s:*' docs from mtproto_state, then boot one.",
        cfg.mtproto_session,
    )
    try:
        await stop()
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        log.debug("MTProto park-teardown failed (non-fatal): %s", exc)


# ───────────────────────── Identity resolution ─────────────────────── #


async def _fetch_user(target_id: int) -> User | None:
    """Single peer lookup shared by resolve_user and is_bot_user.

    Returns the raw peer, or None when the client is down, the lookup
    times out, or the peer is unknown/rate-limited. Cancellation propagates.
    """
    c: Client | None = _client
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
        await _park_on_auth_failure(exc)
        wait = getattr(exc, "value", None)
        if wait is not None:
            log.warning("MTProto FloodWait for %d: retry in %ss.", target_id, wait)
        else:
            log.debug("MTProto resolve failed for %d: %s", target_id, exc)
        return None


async def resolve_user(target_id: int) -> tuple[str, str | None, str | None] | None:
    """Resolve (first_name, username, last_name) for a user ID via MTProto.

    Returns None when the client is not running (not started or stopped),
    when it drops mid-run, or when the peer is unknown, rate-limited, or nameless:
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
    c: Client | None = _client
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
        await _park_on_auth_failure(exc)
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
    refuse bot targets; client down, unknown peer, flood, a non-user peer
    (a group or channel id), and a nameless user all map to None (unknown,
    never False-as-fact).
    """
    user = await _fetch_user(target_id)
    if user is None or not getattr(user, "first_name", ""):
        return None
    is_bot = getattr(user, "is_bot", None)
    if is_bot is None:
        return None
    return bool(is_bot)


# ──────────────────────── Member harvest ────────────────────────── #


@dataclass(frozen=True)
class HarvestResult:
    """Outcome of one resumable member-harvest slice."""

    harvested: int
    scanned: int
    complete: bool
    next_offset: int


def _harvest_state_id(chat_id: int) -> str:
    """Return the durable state key of one group's harvest cursor."""
    return f"{cfg.mtproto_session}:harvest:{chat_id}"


async def _load_harvest_offset(chat_id: int) -> int:
    """Return the member position where the last slice stopped.

    The cursor read is a normal database call, so it runs through the
    shared circuit and call budget like every other read: a stalled
    database must fail this slice quickly instead of holding the harvest
    for the driver's socket timeout.
    """
    try:
        row = await db_call(
            lambda: fetch_one(
                select(mtproto_state.c.value).where(
                    mtproto_state.c.id == _harvest_state_id(chat_id)
                )
            )
        )
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        log.debug("Member harvest state read failed for %d: %s", chat_id, exc)
        return 0
    raw = row.get("value") if row else None
    if not isinstance(raw, bytes | bytearray):
        return 0
    try:
        payload = msgspec.json.decode(bytes(raw))
    except Exception:
        return 0
    if not isinstance(payload, dict) or payload.get("complete") is True:
        return 0
    offset = payload.get("offset")
    return int(offset) if isinstance(offset, int) and offset > 0 else 0


async def _save_harvest_state(chat_id: int, offset: int, *, complete: bool) -> None:
    """Persist the harvest cursor; a failed write only loses resume progress."""
    payload = msgspec.json.encode({"offset": max(0, offset), "complete": complete})
    try:
        await db_call(
            lambda: run(
                pg_insert(mtproto_state)
                .values(
                    id=_harvest_state_id(chat_id),
                    value=payload,
                    updated_on=int(utc_now().timestamp()),
                )
                .on_conflict_do_update(
                    index_elements=["id"],
                    set_={
                        "value": payload,
                        "updated_on": int(utc_now().timestamp()),
                    },
                )
            )
        )
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        log.debug("Member harvest state write failed for %d: %s", chat_id, exc)


async def harvest_group_members_result(
    chat_id: int, *, limit: int = 1000
) -> HarvestResult:
    """Cache a resumable slice of *chat_id*'s members.

    The scan resumes at the offset the previous slice stored, so a group
    larger than one time budget is covered by successive runs instead of
    always restarting at the first member. A slice that reaches the end of
    the member list resets the cursor; a slice that stops on the budget or
    a flood wait keeps it for the next run.
    """
    from tcbot.database import users_cache  # noqa: PLC0415 (avoid import cycle)

    c = _client
    if _auth_dead:
        raise RuntimeError("MTProto session invalidated; refusing to harvest.")
    if c is None or not c.is_connected:
        raise RuntimeError("MTProto client is not connected.")
    offset = await _load_harvest_offset(chat_id)
    requested_limit = offset + limit
    if offset:
        log.info("Member harvest for %d resumes at position %d.", chat_id, offset)
    deadline = monotonic() + _HARVEST_BUDGET_S
    _HARVEST_BATCH: int = 50
    pending: list = []
    count = 0
    position = 0
    scanned = 0

    async def _flush() -> None:
        nonlocal count
        if not pending:
            return
        batch = list(pending)
        try:
            results = await gather_bounded(batch)
        finally:
            for coro in batch:
                if inspect.getcoroutinestate(coro) == inspect.CORO_CREATED:
                    coro.close()
            pending.clear()
        for result in results:
            if isinstance(result, BaseException):
                log.debug("Member harvest write failed: %s", result)
            else:
                count += 1

    async def _harvest_member(
        group_id: int,
        user_id: int,
        username: str | None,
        first_name: str,
        last_name: str | None,
    ) -> bool:
        """Write the identity and its group membership in one batch item."""
        harvested = await users_cache.harvest_user_identity(
            user_id, username, first_name, last_name
        )
        try:
            await users_cache.touch_chat_member(group_id, user_id)
        except Exception as exc:
            log.debug("Membership harvest write failed for %d: %s", user_id, exc)
        return harvested

    try:
        async for member in c.get_chat_members(chat_id, limit=requested_limit):
            position += 1
            if position <= offset:
                continue
            if monotonic() >= deadline:
                await _flush()
                await _save_harvest_state(chat_id, position - 1, complete=False)
                log.warning(
                    "Member harvest stopped on timeslice in %d at position %d "
                    "(%ds budget); the next run resumes there.",
                    chat_id,
                    position - 1,
                    int(_HARVEST_BUDGET_S),
                )
                return HarvestResult(
                    count, scanned, complete=False, next_offset=position - 1
                )
            user = getattr(member, "user", None)
            fname = getattr(user, "first_name", None) if user is not None else None
            if user is None or getattr(user, "is_bot", False) or not fname:
                continue
            scanned += 1
            pending.append(
                _harvest_member(
                    chat_id,
                    user.id,
                    getattr(user, "username", None),
                    fname,
                    getattr(user, "last_name", None),
                )
            )
            if len(pending) >= _HARVEST_BATCH:
                await _flush()
                await _save_harvest_state(chat_id, position, complete=False)
        await _flush()
        # * A full requested slice may have more members behind it. Only a
        # * short slice proves the end of the list.
        if position < requested_limit:
            await _save_harvest_state(chat_id, 0, complete=True)
            return HarvestResult(count, scanned, complete=True, next_offset=0)
        await _save_harvest_state(chat_id, position, complete=False)
        return HarvestResult(count, scanned, complete=False, next_offset=position)
    except Exception as exc:
        if getattr(exc, "value", None) is not None:  # FloodWait-likes carry .value
            log.warning("Member harvest stopped early in %d: %s", chat_id, exc)
            try:
                await _flush()
            except asyncio.CancelledError:
                raise
            except Exception as flush_exc:
                log.debug("Member harvest partial flush failed: %s", flush_exc)
            await _save_harvest_state(chat_id, position, complete=False)
            return HarvestResult(count, scanned, complete=False, next_offset=position)
        await _save_harvest_state(chat_id, position, complete=False)
        await _park_on_auth_failure(exc)
        raise
    finally:
        for coro in pending:
            if inspect.getcoroutinestate(coro) == inspect.CORO_CREATED:
                coro.close()


async def harvest_group_members(chat_id: int, *, limit: int = 1000) -> int:
    """Cache one member-harvest slice and return the identities harvested."""
    result = await harvest_group_members_result(chat_id, limit=limit)
    return result.harvested
