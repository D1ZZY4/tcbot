# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Admin CRUD for federation admin membership."""

from __future__ import annotations

from tcbot.database.cache import effective_role_cache
from tcbot.database.documents import AdminDoc
from tcbot.database.mongos import col, db_call
from tcbot.utils.logger import get_logger
from tcbot.utils.time_and_date import utc_now

# * Logger keeps the pre-split name so log output is unchanged.
log = get_logger("tcbot.database.users_roles")


async def is_admin(user_id: int) -> bool:
    """Return True if user_id is a registered admin."""
    return (
        await db_call(col("tc_admins").find_one({"user_id": user_id}, {"_id": 1}))
        is not None
    )


async def add_admin(user_id: int, promoted_by: int) -> None:
    """Add a new admin via upsert; no-op if already present."""
    await db_call(
        col("tc_admins").update_one(
            {"user_id": user_id},
            {
                "$setOnInsert": {
                    "user_id": user_id,
                    "promoted_by": promoted_by,
                    "promoted_date": utc_now(),
                }
            },
            upsert=True,
        )
    )
    effective_role_cache.invalidate(user_id)


async def remove_admin(user_id: int) -> bool:
    """Remove an admin; return True if the entry was deleted."""
    r = await db_call(col("tc_admins").delete_one({"user_id": user_id}))
    effective_role_cache.invalidate(user_id)
    return r.deleted_count > 0


async def all_admins() -> list[AdminDoc]:
    """Return all admin documents."""
    return await db_call(
        col("tc_admins").find({}, {"_id": 0, "user_id": 1}).to_list(None)
    )


async def admin_count() -> int:
    """Return the total count of registered admins."""
    return await db_call(col("tc_admins").estimated_document_count())
