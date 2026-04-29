# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""MongoDB connection and collection references."""
from typing import Any, Dict

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorCollection

from .. import DB_NAME, MONGODB_URI

_client = AsyncIOMotorClient(MONGODB_URI)
db = _client[DB_NAME]

# Typed collection handles to help static analysis (documents are dicts)
federated_groups: AsyncIOMotorCollection[Dict[str, Any]] = db["federated_groups"]
tc_owners: AsyncIOMotorCollection[Dict[str, Any]] = db["tc_owners"]
tc_admins: AsyncIOMotorCollection[Dict[str, Any]] = db["tc_admins"]
bans: AsyncIOMotorCollection[Dict[str, Any]] = db["bans"]
promotion_requests: AsyncIOMotorCollection[Dict[str, Any]] = db["promotion_requests"]
pending_joins: AsyncIOMotorCollection[Dict[str, Any]] = db["pending_joins"]
member_cache: AsyncIOMotorCollection[Dict[str, Any]] = db["member_cache"]


async def init_db() -> None:
    """Create indexes for all collections on startup."""
    await federated_groups.create_index("chat_id", unique=True)
    await tc_owners.create_index("user_id", unique=True)
    await tc_admins.create_index("user_id", unique=True)
    await bans.create_index("ban_id", unique=True)
    await bans.create_index([("banned_user_id", 1), ("is_active", 1)])
    await promotion_requests.create_index("request_id", unique=True)
    await promotion_requests.create_index([("target_id", 1), ("status", 1)])
    await pending_joins.create_index("chat_id", unique=True)
    await member_cache.create_index("user_id", unique=True)
