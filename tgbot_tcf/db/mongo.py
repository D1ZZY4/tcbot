# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""MongoDB connection and collection references."""
from motor.motor_asyncio import AsyncIOMotorClient

from ..config import DB_NAME, MONGODB_URI

_client = AsyncIOMotorClient(MONGODB_URI)
db = _client[DB_NAME]

federated_groups = db["federated_groups"]
tc_owners = db["tc_owners"]
tc_admins = db["tc_admins"]
bans = db["bans"]
promotion_requests = db["promotion_requests"]


async def init_db() -> None:
    """Create indexes for all collections on startup."""
    await federated_groups.create_index("chat_id", unique=True)
    await tc_owners.create_index("user_id", unique=True)
    await tc_admins.create_index("user_id", unique=True)
    await bans.create_index("ban_id", unique=True)
    await bans.create_index([("banned_user_id", 1), ("is_active", 1)])
    await promotion_requests.create_index("request_id", unique=True)
    await promotion_requests.create_index([("target_id", 1), ("status", 1)])
