# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Federation staff role helpers (tc_owners, tc_admins, and tc_roles)."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Literal, cast

from pymongo.errors import DuplicateKeyError

from tcbot.database.cache import (
    _OWNER_KEY,
    effective_role_cache,
    owner_id_cache,
)
from tcbot.database.documents import AdminDoc, RoleDoc, RoleRefDoc
from tcbot.database.mongos import col, db_call
from tcbot.database.types import UserId
from tcbot.utils.dispatch import throw_if_cancelled
from tcbot.utils.logger import get_logger
from tcbot.utils.time_and_date import utc_now

if TYPE_CHECKING:
    from datetime import datetime

log = get_logger(__name__)

# ────────────────────── Role hierarchy tables ───────────────────── #
# * Numeric ranks compare executor vs target; labels render to humans.

VALID_ROLES: tuple[Literal["developer", "tester"], ...] = ("developer", "tester")

ROLE_RANK: dict[str, int] = {
    "founder": 4,
    "admin": 3,
    "developer": 2,
    "tester": 1,
}

ROLE_LABEL: dict[str, str] = {
    "founder": "Founder",
    "admin": "Admin",
    "developer": "Developer",
    "tester": "Tester",
}


def role_rank(role: str | None) -> int:
    """Convert a role string to its numeric rank value for comparison."""
    return ROLE_RANK.get(role or "", 0)


# ───────────────────────── Owner CRUD ────────────────────────── #


async def get_owner_id(*, fresh: bool = False) -> int | None:
    """Return the current owner's user ID (L1->L2->DB cached).

    With ``fresh=True`` the cache is bypassed and the row is read directly
    from MongoDB, then the cache is refreshed. Enforcement decisions use
    ``fresh=True`` so a transfer in another process is never hidden for
    up to the 300 s owner TTL; display reads keep the cached fast path.
    """

    async def _fetch() -> int | None:
        doc: AdminDoc | None = await db_call(
            lambda: col("tc_owners").find_one(
                {}, {"_id": 0, "user_id": 1}, sort=[("user_id", 1)]
            )
        )
        return doc["user_id"] if doc else None

    if fresh:
        owner = await _fetch()
        owner_id_cache.put(_OWNER_KEY, owner)
        return owner
    return cast("int | None", await owner_id_cache.get_or_fetch(_OWNER_KEY, _fetch))


async def is_owner(user_id: int, *, fresh: bool = False) -> bool:
    """Return True if user_id belongs to the bot owner.

    Served from the cached owner ID (300 s L1 TTL, invalidated on
    transfer) instead of a dedicated ``find_one`` so hot auth paths pay
    zero MongoDB round trips on cache hits. Errors propagate like the
    previous direct read so decorators keep their fail-closed retry reply.

    With ``fresh=True`` the owner row is read directly from MongoDB
    (mirroring ``get_owner_id(fresh=True)``) so an ownership transfer in
    another process is never hidden for up to the 300 s owner TTL.
    Enforcement gates use it; display reads keep the cached fast path.
    """
    return (await get_owner_id(fresh=fresh)) == user_id


async def ensure_initial_owner(initial_id: int) -> None:
    """Create the first owner entry if the owners collection is empty."""
    if await db_call(lambda: col("tc_owners").estimated_document_count()) > 0:
        return
    try:
        await db_call(lambda: col("tc_owners").insert_one({"user_id": initial_id}))
        owner_id_cache.put(_OWNER_KEY, initial_id)
    except DuplicateKeyError:
        # * Another instance won the startup race; drop the cache so the next read refreshes.
        owner_id_cache.invalidate(_OWNER_KEY)


async def set_owner(user_id: int) -> None:
    """Replace the current owner with user_id; clears the role cache."""
    # * Single upsert write: find_one_and_replace on an empty filter inserts
    # * when the collection is empty and replaces the lowest-id row
    # * otherwise, so a mid-flight crash can never leave zero owner rows
    # * (the old insert-then-delete pair could). A leftover second row from
    # * an earlier split brain is still removed below for convergence; the
    # * delete retries briefly so a transient failure cannot strand two
    # * owner rows without operator guidance.
    await db_call(
        lambda: col("tc_owners").find_one_and_replace(
            {},
            {"user_id": user_id},
            upsert=True,
            sort=[("user_id", 1)],
        )
    )
    # * Convergence delete with a bounded retry: a transient failure backs
    # * off and retries (three attempts total), while a persistent failure
    # * logs operator guidance and still raises so the transfer fails closed
    # * exactly as before. Cancellation propagates immediately.
    for attempt in range(3):
        try:
            await db_call(
                lambda: col("tc_owners").delete_many({"user_id": {"$ne": user_id}})
            )
            break
        except asyncio.CancelledError:
            raise
        except Exception:
            if attempt < 2:
                await asyncio.sleep(0.5 * (attempt + 1))
                continue
            log.exception(
                "set_owner cleanup delete failed for user %d: tc_owners may "
                "still hold two owner rows (split brain). Owner resolution "
                "picks the lowest user_id, so the previous Founder can be "
                "left without founder or admin role. Inspect the tc_owners "
                "collection and delete the row whose user_id != %d manually, "
                "then retry the transfer.",
                user_id,
                user_id,
            )
            raise
    owner_id_cache.put(_OWNER_KEY, user_id)
    # * The two writes above are not atomic: a crash between them can leave
    # * one or two owner rows (never zero; the first write upserts). Verify
    # * the invariant and log loudly so a split brain is noticed instead of
    # * serving nondeterministic owners.
    try:
        owner_rows = await db_call(lambda: col("tc_owners").estimated_document_count())
    except Exception:
        log.exception("set_owner verification read failed for user %d", user_id)
    else:
        if owner_rows != 1:
            log.error(
                "set_owner left %d owner rows for user %d; expected exactly 1.",
                owner_rows,
                user_id,
            )
    # * Full two-layer invalidation: old owner's ID is unknown, so we cannot
    # * call invalidate(old_id).  clear_all() sweeps L1 + all Redis keys with
    # * the "role" prefix so no process reads a stale "founder" role after the
    # * transfer completes.
    await effective_role_cache.clear_all()


# ───────────────────────── Admin CRUD ────────────────────────── #


async def is_admin(user_id: int) -> bool:
    """Return True if user_id is a registered admin."""
    return (
        await db_call(
            lambda: col("tc_admins").find_one({"user_id": user_id}, {"_id": 1})
        )
        is not None
    )


async def add_admin(user_id: int, promoted_by: int) -> None:
    """Add a new admin via upsert; no-op if already present."""
    await db_call(
        lambda: col("tc_admins").update_one(
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
    r = await db_call(lambda: col("tc_admins").delete_one({"user_id": user_id}))
    effective_role_cache.invalidate(user_id)
    return r.deleted_count > 0


async def all_admins() -> list[AdminDoc]:
    """Return all admin documents."""
    return await db_call(
        lambda: list(col("tc_admins").find({}, {"_id": 0, "user_id": 1}))
    )


async def admin_count() -> int:
    """Return the total count of registered admins."""
    return await db_call(lambda: col("tc_admins").estimated_document_count())


# ──────────────────────── Custom roles ────────────────────────── #


async def set_role(user_id: int, role: str, assigned_by: int) -> None:
    """Assign a custom role (developer/tester) to a user."""
    # ! CRITICAL: reject anything outside VALID_ROLES. get_effective_role
    # ! returns the stored value verbatim, so a stored "admin" or "founder"
    # ! would grant real privilege to a tc_roles row.
    if role not in VALID_ROLES:
        raise ValueError(f"Refusing to store invalid custom role: {role!r}")
    row: RoleDoc = {
        "user_id": UserId(user_id),
        "role": role,
        "assigned_by": UserId(assigned_by),
        "assigned_at": utc_now(),
    }
    await db_call(
        lambda: col("tc_roles").update_one(
            {"user_id": user_id},
            {"$set": row},
            upsert=True,
        )
    )
    effective_role_cache.invalidate(user_id)


async def remove_role(user_id: int) -> bool:
    """Remove a user's custom role from the database."""
    r = await db_call(lambda: col("tc_roles").delete_one({"user_id": user_id}))
    effective_role_cache.invalidate(user_id)
    return r.deleted_count > 0


async def get_role(user_id: int) -> str | None:
    """Get a user's custom role from the database only."""
    doc = await db_call(
        lambda: col("tc_roles").find_one({"user_id": user_id}, {"role": 1})
    )
    return doc["role"] if doc else None


async def all_by_role(role: str) -> list[RoleRefDoc]:
    """Get all users with a specific custom role."""
    return await db_call(
        lambda: list(col("tc_roles").find({"role": role}, {"_id": 0, "user_id": 1}))
    )


async def role_count(role: str) -> int:
    """Count role members (count-only views; avoids fetching documents)."""
    return await db_call(lambda: col("tc_roles").count_documents({"role": role}))


# ─────────────────────── Role resolution ──────────────────────── #


async def is_staff(user_id: int, *, fresh: bool = False) -> bool:
    """Return True if user_id is owner or admin.

    Served from the cached effective role (60 s L1 TTL) instead of two
    uncached ``find_one`` reads. Lookup failures keep the historical
    contract: log at warning level and return False (callers that need a
    retry hint on outage should use ``get_effective_role`` directly, as
    the appeal-review path and the auth decorators do). Cancellation
    still propagates.

    With ``fresh=True`` the effective role is read directly from MongoDB
    so a demotion in another process is never hidden for up to the 60 s
    role TTL. Enforcement gates use it; display reads keep the cached
    fast path.
    """
    try:
        role = await get_effective_role(user_id, fresh=fresh)
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
    (decorators, re-checks, demote repair, threshold ban exemption, appeal
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
                    lambda: col("tc_owners").find_one(
                        {"user_id": user_id}, {"_id": 1}, sort=[("user_id", 1)]
                    )
                )
                return doc is not None

            owner, admin, role = await asyncio.gather(
                _owner_direct(),
                is_admin(user_id),
                get_role(user_id),
                return_exceptions=True,
            )
        else:
            owner, admin, role = await asyncio.gather(
                is_owner(user_id),
                is_admin(user_id),
                get_role(user_id),
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
            lambda: col("tc_admins").find_one(
                {"user_id": user_id},
                {"_id": 0, "promoted_by": 1, "promoted_date": 1},
            )
        )
        if doc:
            return role, doc.get("promoted_by"), doc.get("promoted_date")
        return role, None, None
    doc = await db_call(
        lambda: col("tc_roles").find_one(
            {"user_id": user_id},
            {"_id": 0, "assigned_by": 1, "assigned_at": 1},
        )
    )
    if doc:
        return role, doc.get("assigned_by"), doc.get("assigned_at")
    return role, None, None


__all__ = [
    "ROLE_LABEL",
    "ROLE_RANK",
    "VALID_ROLES",
    "add_admin",
    "admin_count",
    "all_admins",
    "all_by_role",
    "effective_role_cache",
    "ensure_initial_owner",
    "get_effective_role",
    "get_owner_id",
    "get_role",
    "is_admin",
    "is_owner",
    "is_staff",
    "owner_id_cache",
    "remove_admin",
    "remove_role",
    "role_count",
    "role_meta",
    "role_rank",
    "set_owner",
    "set_role",
]
