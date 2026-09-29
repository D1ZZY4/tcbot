# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""MongoDB client lifecycle, accessors, and shared client options."""

from __future__ import annotations

import secrets
import string
from pathlib import Path
from typing import TYPE_CHECKING, Any

import certifi
from motor.motor_asyncio import (
    AsyncIOMotorClient,
    AsyncIOMotorCollection,
    AsyncIOMotorDatabase,
)

from tcbot import cfg
from tcbot.utils.circuit_breaker import mongodb as _mongo_cb
from tcbot.utils.logger import get_logger

if TYPE_CHECKING:
    from collections.abc import Awaitable

_RESOLV_CONF = "/etc/resolv.conf"

# * Logger keeps the pre-split name so log output is unchanged.
log = get_logger("tcbot.database.mongos")


def _patch_dns_if_needed() -> None:
    """Install an in-process fallback resolver when /etc/resolv.conf is absent."""
    if not Path(_RESOLV_CONF).exists():
        try:
            import dns.resolver  # noqa: PLC0415 (optional dependency; lazy import avoids ImportError when dnspython is absent)

            resolver = dns.resolver.Resolver(configure=False)
            resolver.nameservers = ["8.8.8.8", "8.8.4.4"]
            dns.resolver.default_resolver = resolver
        except Exception as exc:
            log.debug("DNS patch skipped: %s", exc)


_db: AsyncIOMotorDatabase | None = None
_client: AsyncIOMotorClient | None = None

_ID_ALPHABET: str = string.ascii_lowercase + string.digits

# ──────────────── MongoDB Connection Pool Parameters ────────────── #
_MONGO_SERVER_SELECTION_MS: int = 10_000
_MONGO_CONNECT_TIMEOUT_MS: int = 10_000
_MONGO_SOCKET_TIMEOUT_MS: int = 45_000
_MONGO_MAX_POOL_SIZE: int = 20
_MONGO_MIN_POOL_SIZE: int = 2
_MONGO_MAX_IDLE_MS: int = 60_000
_MONGO_HEARTBEAT_MS: int = 30_000

# ──────────────────────── Index TTL Constants ───────────────────── #
# * MongoDB TTL index for member_cache: auto-expire docs after 90 days.
# * 90 days * 86400 s/day = 7776000 s; split into named parts so the
# * intent is obvious and adjustable without hunting for a raw literal.
_MEMBER_CACHE_TTL_DAYS: int = 90
_MEMBER_CACHE_EXPIRE_S: int = _MEMBER_CACHE_TTL_DAYS * 86_400


def make_short_id(length: int = 10) -> str:
    """Generate a random URL-safe lowercase alphanumeric ID."""
    return "".join(secrets.choice(_ID_ALPHABET) for _ in range(length))


def db() -> AsyncIOMotorDatabase:
    """Get the main MongoDB database instance."""
    if _db is None:
        raise RuntimeError("DB not initialised; call connect() first.")
    return _db


def mongo_client_kwargs() -> dict[str, Any]:
    """Extra MongoClient kwargs shared by every MongoDB client in the process.

    Pins TLS trust to the certifi Mozilla bundle. Sandboxes without a
    usable system CA store (empty /etc/ssl/certs) fail Atlas handshakes
    with CERTIFICATE_VERIFY_FAILED ("unable to get local issuer
    certificate"); certifi is current where the system store is not.
    Skipped when the URI already carries its own tlsCAFile so an
    operator override always wins; ignored for non-TLS schemes.
    Shared by the async Motor client below and the scheduler's separate
    synchronous client (APScheduler builds its own ``MongoClient`` for
    ``MongoDBJobStore``, so it needs the same pinning or scheduler
    startup dies with the identical TLS error while Motor connects fine).
    """
    if "tlscafile" not in cfg.mongodb_uri.lower():
        kwargs: dict[str, Any] = {"tlsCAFile": certifi.where()}
    else:
        kwargs = {}
    # * Shared by Motor and the APScheduler jobstore's own sync client: the
    # * latter drops to pymongo's 30s server-selection default otherwise and
    # * blocks the event loop at every boot under a degraded MongoDB.
    kwargs.setdefault("serverSelectionTimeoutMS", _MONGO_SERVER_SELECTION_MS)
    kwargs.setdefault("connectTimeoutMS", _MONGO_CONNECT_TIMEOUT_MS)
    return kwargs


def mongo_jobstore_kwargs() -> dict[str, Any]:
    """Extra MongoClient kwargs for the APScheduler MongoDBJobStore client.

    Kept separate from :func:`mongo_client_kwargs` (whose selection/connect
    timeouts ``connect()`` already shares): the job store's synchronous
    client additionally needs socket and pool bounds so a hung socket
    cannot stall the scheduler thread's borrowed event loop, and so the
    store never opens more connections than its single-threaded use needs.
    """
    return {
        "socketTimeoutMS": _MONGO_SOCKET_TIMEOUT_MS,
        "maxPoolSize": 2,
        "minPoolSize": 0,
        "maxIdleTimeMS": _MONGO_MAX_IDLE_MS,
        "heartbeatFrequencyMS": _MONGO_HEARTBEAT_MS,
    }


async def connect() -> None:
    """Establish MongoDB connection and initialize the global _db instance."""
    global _client, _db
    _patch_dns_if_needed()
    client_kwargs = mongo_client_kwargs()
    # * serverSelection/connect timeouts live in mongo_client_kwargs() (shared
    # * with the scheduler's sync client): passing them here as well would be
    # * a duplicate keyword argument and crash startup with TypeError.
    client = AsyncIOMotorClient(
        cfg.mongodb_uri,
        socketTimeoutMS=_MONGO_SOCKET_TIMEOUT_MS,
        maxPoolSize=_MONGO_MAX_POOL_SIZE,
        minPoolSize=_MONGO_MIN_POOL_SIZE,
        maxIdleTimeMS=_MONGO_MAX_IDLE_MS,
        heartbeatFrequencyMS=_MONGO_HEARTBEAT_MS,
        compressors=["zlib"],
        retryWrites=True,
        retryReads=True,
        **client_kwargs,
    )
    await _mongo_cb.call(client.admin.command("ping"))
    _client = client
    _db = client[cfg.db_name]
    log.info("MongoDB connected → %s", cfg.db_name)


def close() -> None:
    """Close the shared client, releasing pooled sockets (shutdown path).

    Called after every drain in ``_post_shutdown`` so no in-flight write
    outlives the pool. Safe to call without a prior connect.
    """
    global _client, _db
    client, _client = _client, None
    _db = None
    if client is not None:
        try:
            client.close()
        except Exception as exc:
            log.debug("MongoDB client close failed (non-fatal): %s", exc)


def col(name: str) -> AsyncIOMotorCollection:
    """Get a MongoDB collection by name."""
    return db()[name]


def is_connected() -> bool:
    """Return True when a MongoDB connection has been established via connect()."""
    return _db is not None


async def db_call[T](coro: Awaitable[T]) -> T:
    """Execute a Motor coroutine through the MongoDB circuit breaker.

    Use this inside database helper modules for operations where a full
    socket-timeout wait is undesirable when the cluster is unreachable.

    Raises:
        CircuitOpenError: Circuit is OPEN; the call was rejected without
            touching MongoDB.
        Any exception the coroutine raises (also recorded as a failure;
            the exception propagates to the caller unchanged).

    """
    return await _mongo_cb.call(coro)
