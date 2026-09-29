# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""MongoDB connection manager - single client shared across the entire application."""

from __future__ import annotations

from .client import (
    _ID_ALPHABET,
    _MEMBER_CACHE_EXPIRE_S,
    _MEMBER_CACHE_TTL_DAYS,
    _MONGO_CONNECT_TIMEOUT_MS,
    _MONGO_HEARTBEAT_MS,
    _MONGO_MAX_IDLE_MS,
    _MONGO_MAX_POOL_SIZE,
    _MONGO_MIN_POOL_SIZE,
    _MONGO_SERVER_SELECTION_MS,
    _MONGO_SOCKET_TIMEOUT_MS,
    _RESOLV_CONF,
    _client,
    _db,
    _patch_dns_if_needed,
    close,
    col,
    connect,
    db,
    db_call,
    is_connected,
    log,
    make_short_id,
    mongo_client_kwargs,
    mongo_jobstore_kwargs,
)
from .indexes import (
    _LEGACY_UNTIL_DATE_INDEX,
    _drop_legacy_active_mutes_index,
    ensure_indexes,
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
    "log",
    "make_short_id",
    "mongo_client_kwargs",
    "mongo_jobstore_kwargs",
]
