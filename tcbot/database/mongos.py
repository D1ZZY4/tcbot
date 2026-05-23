# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""
MongoDB connection manager - single client shared across the entire application
* Manages the database connection pool and client lifecycle
* Provides collection access shortcuts and index management
* Includes DNS patching for compatibility with restricted environments
"""

from __future__ import annotations

import asyncio
import logging
import os
import secrets
import string

from motor.motor_asyncio import (
    AsyncIOMotorClient,
    AsyncIOMotorCollection,
    AsyncIOMotorDatabase,
)

from tcbot import cfg

_RESOLV_CONF = "/etc/resolv.conf"


# ──────────────────────────── DNS Patch ─────────────────────────── #
# * Fixes DNS resolution issues on platforms without standard resolv.conf
# * Required for Termux/Android and other restricted environments
# * Enables mongodb+srv:// SRV records to work correctly


def _patch_dns_if_needed() -> None:
    """
    On platforms without /etc/resolv.conf (e.g. Termux/Android),
    configure dnspython with a fallback public nameserver so that
    mongodb+srv:// SRV resolution still works.
    * Uses Google's public DNS servers as fallback
    * Only runs if /etc/resolv.conf is not found on the system
    * Silently fails if dnspython isn't installed (unlikely but handled)
    """
    if not os.path.exists(_RESOLV_CONF):
        try:
            import dns.resolver

            resolver = dns.resolver.Resolver(configure=False)
            resolver.nameservers = ["8.8.8.8", "8.8.4.4"]
            dns.resolver.default_resolver = resolver
        except Exception as exc:
            logging.getLogger(__name__).debug("DNS patch skipped: %s", exc)


log = logging.getLogger(__name__)

_db: AsyncIOMotorDatabase | None = None

_ID_ALPHABET: str = string.ascii_lowercase + string.digits


# ────────────────────────── ID Generator ────────────────────────── #
# * Creates unique, URL-safe IDs for database records
# * Uses cryptographically secure random number generation


def make_short_id(length: int = 10) -> str:
    """
    Generate a random URL-safe lowercase alphanumeric ID.
    * Uses secrets.choice for cryptographically secure randomness
    * Default length of 10 provides 36^10 possible combinations
    * Creates collision-resistant IDs for ban_id, request_id, etc.
    """
    return "".join(secrets.choice(_ID_ALPHABET) for _ in range(length))


# ──────────────────────── Client Accessors ──────────────────────── #
# * Safe accessors to get the database instance
# * Prevents accidental use before connection is established


def db() -> AsyncIOMotorDatabase:
    """
    Get the main MongoDB database instance
    ! CRITICAL: Raises RuntimeError if called before connect()
    * Ensures the database is properly initialized before use
    """
    if _db is None:
        raise RuntimeError("DB not initialised – call connect() first.")
    return _db


# ─────────────────────────── Connection ─────────────────────────── #
# * Establishes the main MongoDB connection pool
# * Configures all connection parameters for optimal performance
# ! CRITICAL: Must be called before any database operations


async def connect() -> None:
    """
    Establish MongoDB connection and initialize the global _db instance
    * Applies DNS patch if needed for platform compatibility
    * Configures connection pool with optimized timeout and size settings
    * Pings the database to verify connection before returning
    * Sets up zlib compression and automatic write/retry reads
    """
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


# ─────────────────────────── Index Setup ────────────────────────── #
# * Creates all required database indexes in parallel
# * Improves query performance and enforces data uniqueness
# * Safe to call multiple times - MongoDB ignores existing indexes


async def ensure_indexes() -> None:
    """
    Create all critical collection indexes in parallel. No-op if they already exist.
    * Runs all index creation concurrently using asyncio.gather()
    * Creates unique indexes to prevent duplicate records
    * Creates compound indexes for frequently queried field combinations
    * Logs confirmation once all indexes are ready
    """
    await asyncio.gather(
        col("bans").create_index([("banned_user_id", 1), ("is_active", 1)]),
        col("bans").create_index([("ban_id", 1)], unique=True),
        col("tc_owners").create_index([("user_id", 1)], unique=True),
        col("tc_admins").create_index([("user_id", 1)], unique=True),
        col("tc_roles").create_index([("user_id", 1)], unique=True),
        col("federated_groups").create_index([("chat_id", 1), ("is_active", 1)]),
        col("federated_groups").create_index([("chat_id", 1)], unique=True),
        col("member_cache").create_index([("user_id", 1)], unique=True),
        col("warns").create_index([("user_id", 1), ("chat_id", 1), ("timestamp", -1)]),
        col("warn_counts").create_index([("user_id", 1), ("chat_id", 1)], unique=True),
        col("promotion_requests").create_index([("request_id", 1)], unique=True),
        col("promotion_requests").create_index([("target_id", 1), ("status", 1)]),
    )
    log.info("MongoDB indexes ensured.")


# ─────────────────────── Collection Shortcut ────────────────────── #
# * Convenience function to get a collection by name
# * Wraps the db() accessor for cleaner code


def col(name: str) -> AsyncIOMotorCollection:
    """
    Get a MongoDB collection by name
    * Convenience wrapper around db()[name]
    * Automatically checks that database is initialized
    """
    return db()[name]
