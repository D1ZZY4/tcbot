# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
## MongoDB connection manager – single client shared across the app
from __future__ import annotations

import asyncio
import logging
import os
import secrets
import string

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorCollection, AsyncIOMotorDatabase

from tcbot import cfg

_RESOLV_CONF = "/etc/resolv.conf"

def _patch_dns_if_needed() -> None:
    """On platforms without /etc/resolv.conf (e.g. Termux/Android),
    configure dnspython with a fallback public nameserver so that
    mongodb+srv:// SRV resolution still works."""
    if not os.path.exists(_RESOLV_CONF):
        try:
            import dns.resolver
            resolver = dns.resolver.Resolver(configure=False)
            resolver.nameservers = ["8.8.8.8", "8.8.4.4"]
            dns.resolver.default_resolver = resolver
        except Exception:
            pass

log = logging.getLogger(__name__)

_db: AsyncIOMotorDatabase | None = None

_ID_ALPHABET: str = string.ascii_lowercase + string.digits


def make_short_id(length: int = 10) -> str:
    """Generate a random URL-safe lowercase alphanumeric ID."""
    return "".join(secrets.choice(_ID_ALPHABET) for _ in range(length))


def db() -> AsyncIOMotorDatabase:
    if _db is None:
        raise RuntimeError("DB not initialised – call connect() first.")
    return _db


async def connect() -> None:
    global _db
    _patch_dns_if_needed()
    client = AsyncIOMotorClient(
        cfg.mongodb_uri,
        serverSelectionTimeoutMS=10_000,
        connectTimeoutMS=10_000,
        socketTimeoutMS=45_000,
        maxPoolSize=20,
        minPoolSize=2,
        maxIdleTimeMS=60_000,
        heartbeatFrequencyMS=30_000,
        compressors=["zlib"],
        retryWrites=True,
        retryReads=True,
    )
    _db = client[cfg.db_name]
    await _db.command("ping")
    log.info("MongoDB connected → %s", cfg.db_name)


async def ensure_indexes() -> None:
    """Create all critical collection indexes in parallel. No-op if they already exist."""
    await asyncio.gather(
        col("bans").create_index([("banned_user_id", 1), ("is_active", 1)]),
        col("bans").create_index([("ban_id", 1)], unique=True),
        col("tc_owners").create_index([("user_id", 1)], unique=True),
        col("tc_admins").create_index([("user_id", 1)], unique=True),
        col("tc_roles").create_index([("user_id", 1)], unique=True),
        col("federated_groups").create_index([("chat_id", 1), ("is_active", 1)]),
        col("federated_groups").create_index([("chat_id", 1)], unique=True),
        col("member_cache").create_index([("user_id", 1)], unique=True),
        col("warns").create_index([("user_id", 1), ("chat_id", 1)]),
        col("promotion_requests").create_index([("request_id", 1)], unique=True),
        col("promotion_requests").create_index([("target_id", 1), ("status", 1)]),
    )
    log.info("MongoDB indexes ensured.")


def col(name: str) -> AsyncIOMotorCollection:
    return db()[name]
