# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Custom developer and tester role CRUD."""

from __future__ import annotations

from tcbot.database.cache import effective_role_cache
from tcbot.database.documents import RoleRefDoc
from tcbot.database.mongos import col, db_call
from tcbot.utils.time_and_date import utc_now

from .tables import VALID_ROLES


async def set_role(user_id: int, role: str, assigned_by: int) -> None:
    """Assign a custom role (developer/tester) to a user."""
    # ! CRITICAL: reject anything outside VALID_ROLES. get_effective_role
    # ! returns the stored value verbatim, so a stored "admin" or "founder"
    # ! would grant real privilege to a tc_roles row.
    if role not in VALID_ROLES:
        raise ValueError(f"Refusing to store invalid custom role: {role!r}")
    await db_call(
        col("tc_roles").update_one(
            {"user_id": user_id},
            {
                "$set": {
                    "user_id": user_id,
                    "role": role,
                    "assigned_by": assigned_by,
                    "assigned_at": utc_now(),
                }
            },
            upsert=True,
        )
    )
    effective_role_cache.invalidate(user_id)


async def remove_role(user_id: int) -> bool:
    """Remove a user's custom role from the database."""
    r = await db_call(col("tc_roles").delete_one({"user_id": user_id}))
    effective_role_cache.invalidate(user_id)
    return r.deleted_count > 0


async def get_role(user_id: int) -> str | None:
    """Get a user's custom role from the database only."""
    doc = await db_call(col("tc_roles").find_one({"user_id": user_id}, {"role": 1}))
    return doc["role"] if doc else None


async def all_by_role(role: str) -> list[RoleRefDoc]:
    """Get all users with a specific custom role."""
    return await db_call(
        col("tc_roles").find({"role": role}, {"_id": 0, "user_id": 1}).to_list(None)
    )


async def role_count(role: str) -> int:
    """Count role members (count-only views; avoids fetching documents)."""
    return await db_call(col("tc_roles").count_documents({"role": role}))
