# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""Role management — developer and tester roles stored in tc_roles collection."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from tcbot.database.admins_db import is_admin, is_owner
from tcbot.database.mongos import col

VALID_ROLES: frozenset[str] = frozenset({"developer", "tester"})

ROLE_RANK: dict[str, int] = {
    "founder":   4,
    "admin":     3,
    "developer": 2,
    "tester":    1,
}

ROLE_LABEL: dict[str, str] = {
    "founder":   "Founder",
    "admin":     "Admin",
    "developer": "Developer",
    "tester":    "Tester",
}


def role_rank(role: str | None) -> int:
    """Return the numeric rank for a role string (0 = no role)."""
    return ROLE_RANK.get(role or "", 0)


def _col():
    return col("tc_roles")


## ---------------------------------------------------------------------------
## CRUD
## ---------------------------------------------------------------------------

async def set_role(user_id: int, role: str, assigned_by: int) -> None:
    await _col().update_one(
        {"user_id": user_id},
        {"$set": {
            "user_id":     user_id,
            "role":        role,
            "assigned_by": assigned_by,
            "assigned_at": datetime.now(timezone.utc),
        }},
        upsert=True,
    )


async def remove_role(user_id: int) -> bool:
    r = await _col().delete_one({"user_id": user_id})
    return r.deleted_count > 0


async def get_role(user_id: int) -> str | None:
    doc = await _col().find_one({"user_id": user_id})
    return doc["role"] if doc else None


async def all_by_role(role: str) -> list[dict]:
    return await _col().find({"role": role}).to_list(None)


async def all_roles() -> list[dict]:
    return await _col().find({}).to_list(None)


## ---------------------------------------------------------------------------
## Role resolution helpers
## ---------------------------------------------------------------------------

async def get_effective_role(user_id: int) -> str | None:
    """Resolve a user's effective role: founder › admin › developer › tester › None.

    All three DB checks run in parallel for minimum latency.
    """
    owner, admin, role = await asyncio.gather(
        is_owner(user_id),
        is_admin(user_id),
        get_role(user_id),
    )
    if owner:
        return "founder"
    if admin:
        return "admin"
    return role
