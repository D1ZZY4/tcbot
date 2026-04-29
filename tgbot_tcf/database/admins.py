# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""Repository helpers for ``tc_owners`` and ``tc_admins``.

The Transsion Core role model is intentionally tiny: a single owner document
in ``tc_owners`` and zero-or-more admins in ``tc_admins``. These helpers
encode every legal mutation so the call sites in :mod:`tgbot_tcf.modules`
stay declarative.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, AsyncIterator, Dict, Optional

from .mongo import tc_admins, tc_owners


# ----------------------------------------------------------------- owners

async def get_owner_id() -> Optional[int]:
    """Return the current Transsion Core Owner ``user_id``, or ``None``."""
    doc = await tc_owners.find_one({})
    return doc["user_id"] if doc else None


async def is_owner(user_id: int) -> bool:
    """Return ``True`` when ``user_id`` is the Transsion Core Owner."""
    return await tc_owners.find_one({"user_id": user_id}) is not None


async def ensure_owner_seed(initial_owner_id: int) -> None:
    """Insert ``initial_owner_id`` into ``tc_owners`` if the collection is empty."""
    if await tc_owners.find_one({}) is None:
        await tc_owners.insert_one({"user_id": initial_owner_id})


async def replace_owner(new_owner_id: int) -> None:
    """Replace any existing owner document with ``new_owner_id``."""
    await tc_owners.delete_many({})
    await tc_owners.insert_one({"user_id": new_owner_id})


# ----------------------------------------------------------------- admins

async def is_admin(user_id: int) -> bool:
    """Return ``True`` when ``user_id`` is a Transsion Core Admin."""
    return await tc_admins.find_one({"user_id": user_id}) is not None


async def add_admin(*, user_id: int, promoted_by: int, promoted_date: datetime) -> None:
    """Insert a new admin entry. Caller must check for duplicates first."""
    await tc_admins.insert_one(
        {
            "user_id": user_id,
            "promoted_by": promoted_by,
            "promoted_date": promoted_date,
        }
    )


async def remove_admin(user_id: int) -> bool:
    """Remove an admin entry. Returns ``True`` when a row was deleted."""
    res = await tc_admins.delete_one({"user_id": user_id})
    return res.deleted_count > 0


async def upsert_admin_if_missing(
    *, user_id: int, promoted_by: int, promoted_date: datetime
) -> None:
    """Insert an admin entry only when the user has no existing record."""
    await tc_admins.update_one(
        {"user_id": user_id},
        {
            "$setOnInsert": {
                "user_id": user_id,
                "promoted_by": promoted_by,
                "promoted_date": promoted_date,
            }
        },
        upsert=True,
    )


async def count_admins() -> int:
    return await tc_admins.count_documents({})


def iter_admins() -> AsyncIterator[Dict[str, Any]]:
    return tc_admins.find({})
