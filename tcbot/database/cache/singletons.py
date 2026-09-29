# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Shared TwoLevelCache singletons with per-domain TTL tuning."""

from __future__ import annotations

from tcbot.database.cache.twolevel import TwoLevelCache
from tcbot.database.documents import GroupDoc

# * Unit: seconds. Redis TTL slightly exceeds memory TTL per layer.
_ROLE_CACHE_TTL_S: float = 60.0
_ROLE_REDIS_TTL_S: float = 90.0

# * In-memory entry caps sized to peak users/chats without unbounded growth.
_ROLE_CACHE_MAXSIZE: int = 2048
_USER_MENTION_CACHE_MAXSIZE: int = 4096
_CONNECTED_CACHE_MAXSIZE: int = 512

_CONNECTION_CACHE_TTL_S: float = 120.0
_CONNECTION_REDIS_TTL_S: float = 180.0

_GROUPS_LIST_CACHE_TTL_S: float = 30.0
_GROUPS_LIST_REDIS_TTL_S: float = 45.0

_OWNER_CACHE_TTL_S: float = 300.0
_OWNER_REDIS_TTL_S: float = 360.0

_USER_MENTION_CACHE_TTL_S: float = 300.0
_USER_MENTION_REDIS_TTL_S: float = 600.0

# Populated by users_roles.get_effective_role; invalidated on every role write.
effective_role_cache: TwoLevelCache[str | None] = TwoLevelCache(
    memory_ttl=_ROLE_CACHE_TTL_S,
    redis_ttl=_ROLE_REDIS_TTL_S,
    redis_prefix="role",
    maxsize=_ROLE_CACHE_MAXSIZE,
)

# Populated by groups_db.is_connected; invalidated on add/deactivate.
connected_cache: TwoLevelCache[bool] = TwoLevelCache(
    memory_ttl=_CONNECTION_CACHE_TTL_S,
    redis_ttl=_CONNECTION_REDIS_TTL_S,
    redis_prefix="conn",
    maxsize=_CONNECTED_CACHE_MAXSIZE,
)

# Populated by groups_db.active_groups; invalidated on add/deactivate.
active_groups_cache: TwoLevelCache[list[GroupDoc]] = TwoLevelCache(
    memory_ttl=_GROUPS_LIST_CACHE_TTL_S,
    redis_ttl=_GROUPS_LIST_REDIS_TTL_S,
    redis_prefix="groups",
    maxsize=4,
)
_ALL_GROUPS_KEY: str = "__all__"

# Populated by users_roles.get_owner_id; invalidated on set_owner.
owner_id_cache: TwoLevelCache[int | None] = TwoLevelCache(
    memory_ttl=_OWNER_CACHE_TTL_S,
    redis_ttl=_OWNER_REDIS_TTL_S,
    redis_prefix="owner",
    maxsize=4,
)
_OWNER_KEY: str = "__owner__"

# Populated by users_cache.get_user_mention_data; invalidated on upsert_user.
# JSON round-trip: tuple stored as list, caller casts back to tuple on read.
user_mention_cache: TwoLevelCache[list[str | None]] = TwoLevelCache(
    memory_ttl=_USER_MENTION_CACHE_TTL_S,
    redis_ttl=_USER_MENTION_REDIS_TTL_S,
    redis_prefix="umention",
    maxsize=_USER_MENTION_CACHE_MAXSIZE,
)
