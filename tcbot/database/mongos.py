# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""MongoDB connection manager - single client shared across the entire application."""

from __future__ import annotations

import asyncio
import secrets
import string
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Any

import certifi
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure, ExecutionTimeout, WriteConcernError

from tcbot import cfg
from tcbot.utils.circuit_breaker import mongodb as _mongo_cb
from tcbot.utils.dispatch import gather_bounded
from tcbot.utils.logger import get_logger

if TYPE_CHECKING:
    from collections.abc import Callable

    from pymongo.collection import Collection
    from pymongo.database import Database

log = get_logger(__name__)

_RESOLV_CONF = "/etc/resolv.conf"


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


_db: Database | None = None
_client: MongoClient | None = None

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


def is_transient_mongo_error(exc: BaseException) -> bool:
    """Return True when *exc* signals a connectivity or timeout failure.

    Single owner for Mongo transient classification, shared by the circuit
    breaker predicate below and the MTProto write retry. ``ConnectionFailure``
    covers server selection, failover, and network timeouts (including
    ``AutoReconnect`` and ``ServerSelectionTimeoutError`` subclasses).
    ``ExecutionTimeout`` is a timeout rather than a refusal. A retryable
    write concern matches the replica-set failover label used by the retry
    helper. Client-side operation timeouts report through the documented
    ``PyMongoError.timeout`` property. Application errors such as duplicate
    keys, validation failures, and coding errors are not transient: the
    database answered, so they must never open the circuit.
    """
    if isinstance(exc, (ConnectionFailure, ExecutionTimeout)):
        return True
    # * PyMongo client-side operation timeouts (CSOT) expose this property
    # * so a timeout is distinguishable from a refusal without a type list.
    if getattr(exc, "timeout", False):
        return True
    if isinstance(exc, WriteConcernError):
        return "RetryableWriteError" in (getattr(exc, "details", None) or {}).get(
            "errorLabels", []
        )
    # * Callers wrap database calls in asyncio.timeout for slow-path bounds; a
    # * timeout there is a hang, not an application error.
    return isinstance(exc, TimeoutError)


def _counts_toward_circuit(exc: Exception) -> bool:
    """Circuit predicate: only transient Mongo errors count as failures."""
    return is_transient_mongo_error(exc)


def make_short_id(length: int = 10) -> str:
    """Generate a random URL-safe lowercase alphanumeric ID."""
    return "".join(secrets.choice(_ID_ALPHABET) for _ in range(length))


def db() -> Database:
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
    Shared by the sync pymongo client below and the scheduler's separate
    synchronous client (APScheduler builds its own ``MongoClient`` for
    ``MongoDBJobStore``, so it needs the same pinning or scheduler
    startup dies with the identical TLS error while the main client
    connects fine).
    """
    if "tlscafile" not in cfg.mongodb_uri.lower():
        kwargs: dict[str, Any] = {"tlsCAFile": certifi.where()}
    else:
        kwargs = {}
    # * Shared by the main pymongo client and the APScheduler jobstore's own sync client: the
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
    client = MongoClient(
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
    await _mongo_cb.call(
        asyncio.to_thread(client.admin.command, "ping"),
        count_failure=_counts_toward_circuit,
    )
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


def col(name: str) -> Collection:
    """Get a MongoDB collection by name."""
    return db()[name]


def is_connected() -> bool:
    """Return True when a MongoDB connection has been established via connect()."""
    return _db is not None


async def db_call[T](op: Callable[[], T]) -> T:
    """Execute a synchronous pymongo operation through the MongoDB circuit.

    ``op`` is a zero-argument callable (a thunk) that performs the sync
    operation; it runs in a worker thread so the event loop never blocks.
    Use this inside database helper modules for operations where a full
    socket-timeout wait is undesirable when the cluster is unreachable.

    Only transient Mongo errors (see :func:`is_transient_mongo_error`)
    count toward opening the circuit; application errors propagate without
    recording a failure, so a bad write cannot masquerade as an outage.
    Cancellation propagates immediately; a cancelled background thread may
    still finish its operation, which the atomic read patterns tolerate
    (they can only under-count, never double-count, on a late cancellation).

    Raises:
        CircuitOpenError: Circuit is OPEN; the call was rejected without
            touching MongoDB.
        Any exception the operation raises (propagates to the caller
            unchanged).

    """
    return await _mongo_cb.call(
        asyncio.to_thread(op), count_failure=_counts_toward_circuit
    )


# ──────────────────────────── Indexes ──────────────────────────── #

# * Auto-name shared by the retired plain until_date index and the current
# * TTL one (MongoDB names both "until_date_1").
_LEGACY_UNTIL_DATE_INDEX: str = "until_date_1"


async def _drop_legacy_active_mutes_index() -> None:
    """Drop a pre-TTL ``until_date_1`` index left by older releases.

    Releases before the TTL migration created a plain ``(until_date)``
    index under the same auto-name the TTL variant needs, so creating it
    fails with ``IndexOptionsConflict`` (code 85) and the fail-fast
    startup aborts before serving traffic. Databases already on the TTL
    variant (or fresh ones) skip this: the drop runs only when the
    existing index lacks ``expireAfterSeconds``. Startup has not served
    traffic yet, so the brief window without the single-field index is
    safe: the ``(user_id, until_date)`` compound still serves per-user
    reads, and the TTL recreate lands immediately after.
    """
    try:
        existing = await db_call(lambda: list(col("active_mutes").list_indexes()))
    except Exception as exc:
        log.debug("active_mutes index reconciliation skipped: %s", exc)
        return
    for spec in existing:
        if spec.get("name") != _LEGACY_UNTIL_DATE_INDEX:
            continue
        if "expireAfterSeconds" in spec:
            return
        try:
            await db_call(
                lambda: col("active_mutes").drop_index(_LEGACY_UNTIL_DATE_INDEX)
            )
        except Exception as exc:
            log.warning("Dropping legacy active_mutes index failed: %s", exc)
            return
        log.info("Dropped legacy non-TTL active_mutes.until_date_1 index.")
        return


async def ensure_indexes() -> None:
    """Create all critical collection indexes in parallel. No-op if they already exist.

    Raises the first index failure after logging every failure, so the
    fail-fast checks in ``__main__._post_init`` and ``serverless`` startup
    actually fire. Serving traffic without uniqueness indexes (bans
    ``ban_id``, ``warn_counts`` per-user counter, one-pending-request) risks
    duplicate moderation records, which is worse than a loud startup crash
    that the runner watchdog restarts from.
    """
    # * Sequential pre-step, not part of the gather below: a legacy plain
    # * until_date_1 index must be gone before the TTL recreate runs, or
    # * the recreate conflicts and this same fail-fast fires.
    await _drop_legacy_active_mutes_index()
    # * Each create_index runs through the MongoDB circuit (outages feed the
    # * breaker instead of bypassing it) and the batch is bounded to the
    # * fan-out cap of 10, inside the 20-connection pymongo pool: the old raw
    # * gather fired all of them at once and queued on pool exhaustion.
    index_ops = [
        # * Serves get_active_ban(): filter on banned_user_id + is_active, sort on
        # * timestamp + ban_id. Compound index replaces the separate prefix index below.
        partial(
            col("bans").create_index,
            [
                ("banned_user_id", 1),
                ("is_active", 1),
                ("timestamp", -1),
                ("ban_id", -1),
            ],
        ),
        partial(col("bans").create_index, [("ban_id", 1)], unique=True),
        partial(col("tc_owners").create_index, [("user_id", 1)], unique=True),
        # * Serves user_appeal_count() which filters on banned_user_id + appeal_log_msg_id presence
        partial(
            col("bans").create_index,
            [("banned_user_id", 1), ("appeal_log_msg_id", 1)],
            sparse=True,
        ),
        # * Covering index for active_ban_user_ids() DISTINCT over the
        # * active slice: answers from the index without fetching documents.
        partial(col("bans").create_index, [("is_active", 1), ("banned_user_id", 1)]),
        # * Serves mtproto_store peer lookups by username / phone number.
        partial(col("mtproto_state").create_index, [("usernames", 1)], sparse=True),
        partial(col("mtproto_state").create_index, [("phone_number", 1)], sparse=True),
        # * Serves active_ban_count()/active_bans_page() which filter on is_active only
        partial(
            col("bans").create_index,
            [("is_active", 1), ("timestamp", -1), ("ban_id", -1)],
        ),
        # * Serves /check history: every ban (active+inactive) for a user, newest first
        partial(
            col("bans").create_index,
            [("banned_user_id", 1), ("timestamp", -1), ("ban_id", -1)],
        ),
        partial(col("tc_admins").create_index, [("user_id", 1)], unique=True),
        partial(col("tc_roles").create_index, [("user_id", 1)], unique=True),
        # * Serves users_roles.all_by_role() which filters by role only
        partial(col("tc_roles").create_index, [("role", 1)]),
        partial(
            col("federated_groups").create_index, [("chat_id", 1), ("is_active", 1)]
        ),
        partial(col("federated_groups").create_index, [("chat_id", 1)], unique=True),
        # * pending_joins keyed by chat_id with upsert (one pending per chat)
        partial(col("pending_joins").create_index, [("chat_id", 1)], unique=True),
        partial(col("member_cache").create_index, [("user_id", 1)], unique=True),
        # * Covered-query index: serves get_first_names_batch and get_mention_data_batch
        # * $in on user_id with {first_name,username,last_name} projection; all fields in index
        partial(
            col("member_cache").create_index,
            [("user_id", 1), ("first_name", 1), ("username", 1), ("last_name", 1)],
        ),
        # * Serves batch username lookups and search operations
        partial(col("member_cache").create_index, [("username", 1)]),
        # * Serves user_settings lookups by user: one preference row per user.
        partial(col("user_settings").create_index, [("user_id", 1)], unique=True),
        # * Serves name search operations (case-insensitive search by first_name)
        partial(col("member_cache").create_index, [("first_name", 1)]),
        partial(
            col("warns").create_index,
            [("user_id", 1), ("chat_id", 1), ("timestamp", -1)],
        ),
        # * Serves /check history: every warning for a user across groups
        partial(col("warns").create_index, [("user_id", 1), ("timestamp", -1)]),
        # * Serves get_warns() sorts in both directions (newest-first
        # * paged views and oldest-first full reads).
        partial(
            col("warns").create_index,
            [("user_id", 1), ("chat_id", 1), ("timestamp", 1)],
        ),
        # * Serves warn expiry: delete_many({"timestamp": {"$lt": cutoff}}) COLLSCAN without this
        partial(col("warns").create_index, [("timestamp", 1)]),
        # * Serves migrate_records(): update_many on chat_id alone COLLSCANs
        # * the user_id-led indexes above on every group upgrade otherwise.
        partial(col("warns").create_index, [("chat_id", 1)]),
        partial(
            col("warn_counts").create_index,
            [("user_id", 1), ("chat_id", 1)],
            unique=True,
        ),
        # * Serves warn expiry: delete_many({"updated_at": {"$lt": cutoff}}) COLLSCAN without this
        partial(col("warn_counts").create_index, [("updated_at", 1)]),
        # * Serves user_warn_groups() and federation_warn_count() filter + sort
        partial(
            col("warn_counts").create_index,
            [("user_id", 1), ("count", 1), ("updated_at", -1)],
        ),
        # * Serves migrate_records() on warn_counts (see warns chat_id note).
        partial(col("warn_counts").create_index, [("chat_id", 1)]),
        # * Per-user kick / mute history for /check
        partial(col("kicks").create_index, [("user_id", 1), ("timestamp", -1)]),
        partial(col("mutes").create_index, [("user_id", 1), ("timestamp", -1)]),
        partial(
            col("promotion_requests").create_index, [("request_id", 1)], unique=True
        ),
        partial(
            col("promotion_requests").create_index, [("target_id", 1), ("status", 1)]
        ),
        # * One pending request per user: concurrent promotes for the same
        # * target collapse into a single queue entry instead of duplicates.
        partial(
            col("promotion_requests").create_index,
            [("target_id", 1)],
            unique=True,
            partialFilterExpression={"status": "pending"},
        ),
        # * Serves queues_db.all_pending() which filters on status and sorts
        # * by requested_date; compound avoids an in-memory sort.
        partial(
            col("promotion_requests").create_index,
            [("status", 1), ("requested_date", 1)],
        ),
        partial(col("kicks").create_index, [("chat_id", 1)]),
        partial(col("mutes").create_index, [("chat_id", 1)]),
        partial(col("federated_groups").create_index, [("is_active", 1)]),
        # * active_mutes: one document per muted user (upserted by set_active_mute)
        partial(col("active_mutes").create_index, [("user_id", 1)], unique=True),
        # * Compound for get_active_mute() $or filter on specific user
        partial(col("active_mutes").create_index, [("user_id", 1), ("until_date", 1)]),
        # * TTL doubles as the expiry-filtered fetch index for
        # * active_mute_docs()/get_active_mute(): same key as the retired
        # * plain index, so no separate single-field index is kept.
        # * MongoDB auto-names both "until_date_1" and refuses the duplicate
        # * with IndexOptionsConflict, hence the pre-step drop above.
        # * MongoDB auto-deletes expired timed mutes (until_date <= now).
        # * Permanent mutes (until_date None/missing) are never TTL-expired,
        # * matching the query-time filter in get_active_mute/active_mute_docs,
        # * so this only prunes rows those queries already ignore.
        partial(
            col("active_mutes").create_index, [("until_date", 1)], expireAfterSeconds=0
        ),
        # * TTL index: MongoDB auto-expires member_cache docs older than _MEMBER_CACHE_TTL_DAYS.
        # * Replaces the APScheduler weekly cleanup job, shrinking the scheduler surface.
        partial(
            col("member_cache").create_index,
            [("last_updated", 1)],
            expireAfterSeconds=_MEMBER_CACHE_EXPIRE_S,
        ),
    ]
    results = await gather_bounded([db_call(op) for op in index_ops])
    failed = [r for r in results if isinstance(r, BaseException)]
    if failed:
        for exc in failed:
            log.error("Index creation failed: %s", exc)
        # * Re-raise (preserving cancellation) instead of limping on without
        # * indexes: the startup fail-fast checks depend on this raising.
        raise failed[0]
    log.info(
        "MongoDB indexes ensured (%d/%d succeeded).",
        len(results) - len(failed),
        len(results),
    )


__all__ = [
    "_ID_ALPHABET",
    "_LEGACY_UNTIL_DATE_INDEX",
    "_MEMBER_CACHE_EXPIRE_S",
    "_MEMBER_CACHE_TTL_DAYS",
    "_MONGO_CONNECT_TIMEOUT_MS",
    "_MONGO_HEARTBEAT_MS",
    "_MONGO_MAX_IDLE_MS",
    "_MONGO_MAX_POOL_SIZE",
    "_MONGO_MIN_POOL_SIZE",
    "_MONGO_SERVER_SELECTION_MS",
    "_MONGO_SOCKET_TIMEOUT_MS",
    "_RESOLV_CONF",
    "_client",
    "_db",
    "_drop_legacy_active_mutes_index",
    "_patch_dns_if_needed",
    "close",
    "col",
    "connect",
    "db",
    "db_call",
    "ensure_indexes",
    "is_connected",
    "is_transient_mongo_error",
    "log",
    "make_short_id",
    "mongo_client_kwargs",
    "mongo_jobstore_kwargs",
]
