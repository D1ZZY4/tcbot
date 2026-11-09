# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Effective-role resolution across owner, admin, and custom roles."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, cast

from tcbot.database.cache import effective_role_cache
from tcbot.database.mongos import col, db_call
from tcbot.utils.dispatch import throw_if_cancelled
from tcbot.utils.logger import get_logger

from . import admin as _admin_mod
from . import owner as _owner_mod
from . import roles as _roles_mod
from .tables import VALID_ROLES

if TYPE_CHECKING:
    from datetime import datetime

# * Logger keeps the pre-split name so log output is unchanged.
log = get_logger("tcbot.database.users_roles")


async def is_staff(user_id: int) -> bool:
    """Return True if user_id is owner or admin.

    Served from the cached effective role (60 s L1 TTL) instead of two
    uncached ``find_one`` reads. Lookup failures keep the historical
    contract: log at warning level and return False (callers that need a
    retry hint on outage should use ``get_effective_role`` directly, as
    the appeal-review path and the auth decorators do). Cancellation
    still propagates.
    """
    try:
        role = await get_effective_role(user_id)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        log.warning("is_staff role check failed for %d: %s", user_id, exc)
        return False
    return role in ("founder", "admin")


async def get_effective_role(user_id: int, *, fresh: bool = False) -> str | None:
    """Resolve a user's full effective role including owner/admin status (L1->L2->DB cached).

    With ``fresh=True`` the effective-role, owner, and profile caches are
    bypassed and the three rows are read directly from MongoDB, then the
    effective-role cache is refreshed with the result. Enforcement gates
    (decorators, re-checks, demote repair, auto-ban exemption, appeal
    decisions) use ``fresh=True`` so a demotion in another process is never
    hidden for up to the 60 s role TTL; display reads keep the cached path.
    """

    async def _resolve() -> str | None:
        # * Propagate DB errors so get_or_fetch does not cache a degraded role result.
        # * A false "founder" or "admin" cached for a real error would silently bypass
        # * authorization checks for every subsequent call until TTL expiry.
        # * Fresh reads bypass the owner-id cache as well: owner transfer is
        # * rare, but a stale cached owner would otherwise keep granting
        # * founder for the 300 s owner TTL after the transfer landed.
        if fresh:

            async def _owner_direct() -> bool:
                doc = await db_call(
                    col("tc_owners").find_one(
                        {"user_id": user_id}, {"_id": 1}, sort=[("user_id", 1)]
                    )
                )
                return doc is not None

            owner, admin, role = await asyncio.gather(
                _owner_direct(),
                _admin_mod.is_admin(user_id),
                _roles_mod.get_role(user_id),
                return_exceptions=True,
            )
        else:
            owner, admin, role = await asyncio.gather(
                _owner_mod.is_owner(user_id),
                _admin_mod.is_admin(user_id),
                _roles_mod.get_role(user_id),
                return_exceptions=True,
            )
        # * Explicit cancellation check first: CancelledError is a
        # * BaseException, so the generic branches below would re-raise it
        # * anyway, but spelling it out keeps a future ``except Exception``
        # * refactor from silently swallowing shutdown here.
        throw_if_cancelled((owner, admin, role))
        if isinstance(owner, BaseException):
            raise owner
        if isinstance(admin, BaseException):
            raise admin
        if isinstance(role, BaseException):
            raise role
        if role is not None and role not in VALID_ROLES:
            # ! CRITICAL: set_role rejects these on write, but a legacy or
            # ! hand-edited tc_roles row could still carry "admin"/"founder".
            # ! Returning it verbatim would grant real privilege, so treat
            # ! unknown stored values as no custom role instead of trusting
            # ! the document.
            log.error("Ignoring invalid stored role %r for user %d", role, user_id)
            role = None
        return "founder" if owner else "admin" if admin else role

    if fresh:
        result = await _resolve()
        effective_role_cache.put(user_id, result)
        return result
    return cast(
        "str | None", await effective_role_cache.get_or_fetch(user_id, _resolve)
    )


async def role_meta(user_id: int) -> tuple[str | None, int | None, datetime | None]:
    """Return ``(role, assigned_by, assigned_at)``; owner has no metadata."""
    role = await get_effective_role(user_id)
    if role is None:
        return None, None, None
    if role == "founder":
        # * tc_owners stores only user_id; no metadata to surface.
        return role, None, None
    if role == "admin":
        doc = await db_call(
            col("tc_admins").find_one(
                {"user_id": user_id},
                {"_id": 0, "promoted_by": 1, "promoted_date": 1},
            )
        )
        if doc:
            return role, doc.get("promoted_by"), doc.get("promoted_date")
        return role, None, None
    doc = await db_call(
        col("tc_roles").find_one(
            {"user_id": user_id},
            {"_id": 0, "assigned_by": 1, "assigned_at": 1},
        )
    )
    if doc:
        return role, doc.get("assigned_by"), doc.get("assigned_at")
    return role, None, None
