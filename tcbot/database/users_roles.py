# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Federation staff role helpers (tc_owners, tc_admins, and tc_roles)."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Literal, cast

from sqlalchemy import delete, func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError

from tcbot.database.base import tc_admins, tc_owners, tc_roles
from tcbot.database.cache import (
    _OWNER_KEY,
    effective_role_cache,
    owner_id_cache,
)
from tcbot.database.documents import AdminDoc, RoleDoc, RoleRefDoc
from tcbot.database.engine import (
    constraint_name,
    db_call,
    fetch_all,
    fetch_one,
    fetch_value,
    run,
    run_transaction,
)
from tcbot.database.types import UserId
from tcbot.utils.dispatch import throw_if_cancelled
from tcbot.utils.logger import get_logger
from tcbot.utils.time_and_date import utc_now

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.sql import Executable

log = get_logger(__name__)

# * Advisory lock key for the owner transfer. Any fixed value works as long
# * as it is unique among the locks this application takes; it is scoped
# * to the transaction, so it is released on commit and on rollback.
_OWNER_TRANSFER_LOCK_KEY: int = 7_313_919_265_517_001

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

# * Single owner for the two role sets the moderation paths test against.
# * Open-coding them per call site let a new tier land in ROLE_RANK and be
# * missed by every set check, so the rank gate and the staff gate would
# * disagree about the same user.
# * STAFF_ROLES holds every role that can be demoted (Founder is protected
# * and never demoted); FOUNDER_ADMIN_ROLES holds the roles that count as
# * federation staff for permission gates.
STAFF_ROLES: frozenset[str] = frozenset({"admin", "developer", "tester"})
FOUNDER_ADMIN_ROLES: frozenset[str] = frozenset({"founder", "admin"})

# * Name of the primary key that rejects a duplicate owner row.
_CONSTRAINT_OWNERS_PKEY: str = "tc_owners_pkey"


def role_rank(role: str | None) -> int:
    """Convert a role string to its numeric rank value for comparison."""
    return ROLE_RANK.get(role or "", 0)


def role_label(role: str | None) -> str:
    """Return the human label for a role, falling back to the role itself.

    Single owner for the label lookup, so every surface renders a role the
    same way. A role outside the known set falls back to its own name,
    which keeps a legacy row readable instead of blank.
    """
    if not role:
        return ""
    return ROLE_LABEL.get(role, role.capitalize())


def cache_effective_role(user_id: int, role: str | None) -> None:
    """Store an already-resolved effective role in the cache.

    A tier that resolved the role straight from the database uses this so
    the rank comparison later in the same request reads the value the tier
    validated instead of a stale cache entry.
    """
    effective_role_cache.put(user_id, role)


async def _count(stmt: Executable) -> int:
    """Return the row count of one COUNT query as a plain integer."""
    value = await db_call(lambda: fetch_value(stmt))
    return int(value or 0)


async def _owner_count() -> int:
    """Return how many owner rows the table currently holds."""
    return await _count(select(func.count()).select_from(tc_owners))


# ───────────────────────── Owner CRUD ────────────────────────── #


async def get_owner_id(*, fresh: bool = False) -> int | None:
    """Return the current owner's user ID (L1->L2->DB cached).

    With ``fresh=True`` the cache is bypassed and the row is read directly
    from the owners table, then the cache is refreshed. Enforcement decisions
    use ``fresh=True`` so a transfer in another process is never hidden for
    up to the 300 s owner TTL; display reads keep the cached fast path.
    """

    async def _fetch() -> int | None:
        # * The lowest owner row wins, exactly like the old sorted read.
        row = await db_call(
            lambda: fetch_one(
                select(tc_owners.c.user_id).order_by(tc_owners.c.user_id).limit(1)
            )
        )
        return row["user_id"] if row else None

    if fresh:
        owner = await _fetch()
        owner_id_cache.put(_OWNER_KEY, owner)
        return owner
    return cast("int | None", await owner_id_cache.get_or_fetch(_OWNER_KEY, _fetch))


async def is_owner(user_id: int, *, fresh: bool = False) -> bool:
    """Return True if user_id belongs to the bot owner.

    Served from the cached owner ID (300 s L1 TTL, invalidated on
    transfer) instead of a dedicated row read so hot auth paths pay
    zero database round trips on cache hits. Errors propagate like the
    previous direct read so decorators keep their fail-closed retry reply.

    With ``fresh=True`` the owner row is read directly from the owners
    table (mirroring ``get_owner_id(fresh=True)``) so an ownership
    transfer in another process is never hidden for up to the 300 s owner
    TTL. Enforcement gates use it; display reads keep the cached fast path.
    """
    return (await get_owner_id(fresh=fresh)) == user_id


async def ensure_initial_owner(initial_id: int) -> None:
    """Create the first owner entry if the owners table is empty."""
    if await _owner_count() > 0:
        return
    try:
        await db_call(lambda: run(pg_insert(tc_owners).values(user_id=initial_id)))
        owner_id_cache.put(_OWNER_KEY, initial_id)
    except IntegrityError as insert_error:
        if constraint_name(insert_error) != _CONSTRAINT_OWNERS_PKEY:
            # * Only the owner primary key may lose the startup race. Any
            # * other integrity error is a real defect and must not be
            # * swallowed here.
            raise
        # * Another instance won the startup race; drop the cache so the next read refreshes.
        owner_id_cache.invalidate(_OWNER_KEY)


async def set_owner(user_id: int) -> None:
    """Replace the current owner with user_id; clears the role cache."""

    # * The transfer runs in one transaction: the insert and the
    # * convergence delete commit together, so a crash between them cannot
    # * leave one or two owner rows.
    # * The advisory lock serialises concurrent transfers. Without it two
    # * transfers interleave (insert A, insert B, delete != A, delete != B)
    # * and the table ends up with no owner row at all, which would leave
    # * the whole federation without a Founder until the next restart.
    async def _work(sess: AsyncSession) -> None:
        await sess.execute(
            text("SELECT pg_advisory_xact_lock(:key)"),
            {"key": _OWNER_TRANSFER_LOCK_KEY},
        )
        await sess.execute(
            pg_insert(tc_owners)
            .values(user_id=user_id)
            .on_conflict_do_nothing(index_elements=["user_id"])
        )
        await sess.execute(delete(tc_owners).where(tc_owners.c.user_id != user_id))

    try:
        await run_transaction(_work)
    except asyncio.CancelledError:
        raise
    except Exception:
        # * The transaction rolled back, so the previous owner still holds
        # * the role. Fail the transfer closed and point the operator at
        # * the table, because a silent split brain is worse than a
        # * refused transfer.
        log.exception(
            "set_owner failed for user %d: the transfer was rolled back and "
            "the previous Founder keeps the role. Inspect the tc_owners "
            "table and retry the transfer.",
            user_id,
        )
        raise
    owner_id_cache.put(_OWNER_KEY, user_id)
    # * The transaction above is atomic, so the invariant holds. Verify it
    # * anyway and log loudly, so a split brain is noticed instead of
    # * serving nondeterministic owners.
    try:
        owner_rows = await _owner_count()
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
    row = await db_call(
        lambda: fetch_one(
            select(tc_admins.c.user_id).where(tc_admins.c.user_id == user_id)
        )
    )
    return row is not None


async def add_admin(user_id: int, promoted_by: int) -> None:
    """Add a new admin via upsert; no-op if already present."""
    # * The conflict action is DO NOTHING: a repeated promotion leaves the
    # * stored promoter and promotion date untouched, matching the old
    # * insert-only upsert.
    await db_call(
        lambda: run(
            pg_insert(tc_admins)
            .values(
                user_id=user_id,
                promoted_by=promoted_by,
                promoted_date=utc_now(),
            )
            .on_conflict_do_nothing(index_elements=["user_id"])
        )
    )
    effective_role_cache.invalidate(user_id)


async def remove_admin(user_id: int) -> bool:
    """Remove an admin; return True if the entry was deleted."""
    deleted = await db_call(
        lambda: run(delete(tc_admins).where(tc_admins.c.user_id == user_id))
    )
    effective_role_cache.invalidate(user_id)
    return deleted > 0


async def all_admins() -> list[AdminDoc]:
    """Return all admin documents."""
    rows = await db_call(lambda: fetch_all(select(tc_admins.c.user_id)))
    return cast("list[AdminDoc]", rows)


async def admin_count() -> int:
    """Return the total count of registered admins."""
    return await _count(select(func.count()).select_from(tc_admins))


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
    # * The upsert overwrites the stored role, promoter, and timestamp on
    # * every call: the old write replaced the whole role document.
    await db_call(
        lambda: run(
            pg_insert(tc_roles)
            .values(
                user_id=row["user_id"],
                role=row["role"],
                assigned_by=row["assigned_by"],
                assigned_at=row["assigned_at"],
            )
            .on_conflict_do_update(
                index_elements=["user_id"],
                set_={
                    "role": row["role"],
                    "assigned_by": row["assigned_by"],
                    "assigned_at": row["assigned_at"],
                },
            )
        )
    )
    effective_role_cache.invalidate(user_id)


async def remove_role(user_id: int) -> bool:
    """Remove a user's custom role from the database."""
    deleted = await db_call(
        lambda: run(delete(tc_roles).where(tc_roles.c.user_id == user_id))
    )
    effective_role_cache.invalidate(user_id)
    return deleted > 0


async def get_role(user_id: int) -> str | None:
    """Get a user's custom role from the database only."""
    row = await db_call(
        lambda: fetch_one(select(tc_roles.c.role).where(tc_roles.c.user_id == user_id))
    )
    return row["role"] if row else None


async def all_by_role(role: str) -> list[RoleRefDoc]:
    """Get all users with a specific custom role."""
    rows = await db_call(
        lambda: fetch_all(select(tc_roles.c.user_id).where(tc_roles.c.role == role))
    )
    return cast("list[RoleRefDoc]", rows)


async def role_count(role: str) -> int:
    """Count role members (count-only views; avoids fetching documents)."""
    return await _count(
        select(func.count()).select_from(tc_roles).where(tc_roles.c.role == role)
    )


# ─────────────────────── Role resolution ──────────────────────── #


async def is_staff(user_id: int, *, fresh: bool = False) -> bool:
    """Return True if user_id is owner or admin.

    Served from the cached effective role (60 s L1 TTL) instead of two
    uncached role reads. Lookup failures keep the historical contract: log at
    warning level and return False (callers that need a retry hint on outage
    should use ``get_effective_role`` directly, as the appeal-review path
    and the auth decorators do). Cancellation still propagates.

    With ``fresh=True`` the effective role is read directly from the
    database so a demotion in another process is never hidden for up to the
    60 s role TTL. Enforcement gates use it; display reads keep the cached
    fast path.
    """
    try:
        role = await get_effective_role(user_id, fresh=fresh)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        log.warning("is_staff role check failed for %d: %s", user_id, exc)
        return False
    return role in FOUNDER_ADMIN_ROLES


async def get_effective_role(user_id: int, *, fresh: bool = False) -> str | None:
    """Resolve a user's full effective role including owner/admin status (L1->L2->DB cached).

    With ``fresh=True`` the effective-role, owner, and profile caches are
    bypassed and the three rows are read directly from the database, then the
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
                row = await db_call(
                    lambda: fetch_one(
                        select(tc_owners.c.user_id).where(
                            tc_owners.c.user_id == user_id
                        )
                    )
                )
                return row is not None

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
            lambda: fetch_one(
                select(tc_admins.c.promoted_by, tc_admins.c.promoted_date).where(
                    tc_admins.c.user_id == user_id
                )
            )
        )
        if doc:
            return role, doc.get("promoted_by"), doc.get("promoted_date")
        return role, None, None
    doc = await db_call(
        lambda: fetch_one(
            select(tc_roles.c.assigned_by, tc_roles.c.assigned_at).where(
                tc_roles.c.user_id == user_id
            )
        )
    )
    if doc:
        return role, doc.get("assigned_by"), doc.get("assigned_at")
    return role, None, None
