# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""Authorization helpers for Transsion Core role checks."""
from ..db import tc_admins, tc_owners


async def is_tc_owner(user_id: int) -> bool:
    """Return True if the user is the Transsion Core Owner."""
    return await tc_owners.find_one({"user_id": user_id}) is not None


async def is_tc_admin(user_id: int) -> bool:
    """Return True if the user is a Transsion Core Admin (not owner)."""
    return await tc_admins.find_one({"user_id": user_id}) is not None


async def is_authorized(user_id: int) -> bool:
    """Return True if user is TC owner or TC admin."""
    if await is_tc_owner(user_id):
        return True
    return await is_tc_admin(user_id)


async def get_owner_id() -> int | None:
    """Return the current Transsion Core Owner user_id, or None."""
    doc = await tc_owners.find_one({})
    return doc["user_id"] if doc else None
