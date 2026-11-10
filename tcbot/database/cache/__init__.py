# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Two-level cache: codec, memory layer, Redis boundary, and singletons."""

from __future__ import annotations

from tcbot.database.cache.codec import (
    _decode_redis_value,
    _msgspec_enc_hook,
    _tag_scalars,
)
from tcbot.database.cache.memory import CACHE_MISS, TTLCache
from tcbot.database.cache.redis_io import (
    _CLEAR_ALL_TIMEOUT_S,
    _REDIS_GET_TIMEOUT_S,
    _REDIS_WRITE_TIMEOUT_S,
    acquire_redis_client,
    drain_redis_mutations,
    enqueue_redis_mutation,
    redis_client,
)
from tcbot.database.cache.singletons import (
    _ALL_GROUPS_KEY,
    _OWNER_KEY,
    active_groups_cache,
    connected_cache,
    effective_role_cache,
    owner_id_cache,
    user_mention_cache,
)
from tcbot.database.cache.twolevel import TwoLevelCache

__all__ = [
    "CACHE_MISS",
    "_ALL_GROUPS_KEY",
    "_CLEAR_ALL_TIMEOUT_S",
    "_OWNER_KEY",
    "_REDIS_GET_TIMEOUT_S",
    "_REDIS_WRITE_TIMEOUT_S",
    "TTLCache",
    "TwoLevelCache",
    "_decode_redis_value",
    "_msgspec_enc_hook",
    "_tag_scalars",
    "acquire_redis_client",
    "active_groups_cache",
    "connected_cache",
    "drain_redis_mutations",
    "effective_role_cache",
    "enqueue_redis_mutation",
    "owner_id_cache",
    "redis_client",
    "user_mention_cache",
]
