# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Staff role helpers over the role assignment table."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Literal, cast

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from tcbot.database.base import (
    permission_definitions,
    role_assignments,
    role_definitions,
    role_permissions,
    telegram_users,
)
from tcbot.database.cache import (
    _OWNER_KEY,
    effective_role_cache,
    owner_id_cache,
)
from tcbot.database.documents import AdminDoc, RoleDoc, RoleRefDoc
from tcbot.database.engine import (
    db_call,
    fetch_all,
    fetch_one,
    fetch_value,
    run,
    run_transaction,
)
from tcbot.utils.logger import get_logger
from tcbot.utils.time_and_date import utc_now

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.sql import Executable
    from sqlalchemy.sql.elements import ColumnElement

log = get_logger(__name__)

# * Advisory lock key for the owner transfer. Any fixed value works as long
# * as it is unique among the locks this application takes; it is scoped
# * to the transaction, so it is released on commit and on rollback.
_OWNER_TRANSFER_LOCK_KEY: int = 7_313_919_265_517_001

# ────────────────────── Role hierarchy tables ───────────────────── #
# * Numeric ranks compare executor vs target; labels render to humans.

VALID_ROLES: tuple[Literal["developer", "tester"], ...] = ("developer", "tester")

# * Name of a community role. The role argument of every permission gate
# * is typed with it, so a typo in a threshold name is a type error the
# * checker reports instead of a rank that silently matches nobody.
RoleName = Literal["founder", "admin", "developer", "tester"]

# * Spellings the promote command accepts for a role. The table is role
# * vocabulary, so it belongs next to the other role tables rather than
# * in a command module.
ROLE_ALIASES: dict[str, str] = {
    "admin": "admin",
    "developer": "developer",
    "dev": "developer",
    "tester": "tester",
    "test": "tester",
    "moderator": "tester",
    "mod": "tester",
}

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
# * STAFF_ROLES holds every role that can be demoted (the owner is protected
# * and never demoted); FOUNDER_ADMIN_ROLES holds the roles that count as
# * community staff for permission gates.
STAFF_ROLES: frozenset[str] = frozenset({"admin", "developer", "tester"})
FOUNDER_ADMIN_ROLES: frozenset[str] = frozenset({"founder", "admin"})

# * The community catalog names the roles owner, admin, developer, and
# * moderator. The application keeps its own vocabulary for the tiers
# * the handlers compare against, so the translation between the two
# * lives here and the rest of the code never sees a storage key.
ROLE_KEY_BY_APP_ROLE: dict[str, str] = {
    "founder": "owner",
    "admin": "admin",
    "developer": "developer",
    "tester": "moderator",
}
APP_ROLE_BY_ROLE_KEY: dict[str, str] = {
    value: key for key, value in ROLE_KEY_BY_APP_ROLE.items()
}

# * The role the community owner holds.
_OWNER_ROLE: str = ROLE_KEY_BY_APP_ROLE["founder"]
_ADMIN_ROLE: str = ROLE_KEY_BY_APP_ROLE["admin"]


# * An assignment is in force while it is active and its expiry is in the
# * future. The expiry is part of the condition, so it is read here
# * instead of in an index predicate. The predicate is built per call: a
# * timestamp frozen at import time would keep an assignment alive for
# * the whole process lifetime, long after its expiry passed.
def _active_assignment() -> tuple[ColumnElement[bool], ...]:
    """Return the condition that selects the assignments that are in force."""
    return (
        role_assignments.c.status == "active",
        (role_assignments.c.expires_at.is_(None))
        | (role_assignments.c.expires_at > utc_now()),
    )


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
    """Return how many active owner assignments the table currently holds."""
    return await _count(
        select(func.count())
        .select_from(role_assignments)
        .where(role_assignments.c.role_key == _OWNER_ROLE, *_active_assignment())
    )


# ───────────────────────── Owner CRUD ────────────────────────── #


async def get_owner_id(*, fresh: bool = False) -> int | None:
    """Return the current owner's user ID (L1->L2->DB cached).

    With ``fresh=True`` the cache is bypassed and the row is read directly
    from the assignments table, then the cache is refreshed. Enforcement
    decisions use ``fresh=True`` so a transfer in another process is never
    hidden for up to the 300 s owner TTL; display reads keep the cached
    fast path.
    """

    async def _fetch() -> int | None:
        # * The lowest owner row wins, exactly like the old sorted read.
        row = await db_call(
            lambda: fetch_one(
                select(role_assignments.c.user_id)
                .where(
                    role_assignments.c.role_key == _OWNER_ROLE, *_active_assignment()
                )
                .order_by(role_assignments.c.user_id)
                .limit(1)
            )
        )
        return row["user_id"] if row else None

    if fresh:
        # * The refresh publishes the value only when the key was not
        # * invalidated while the read was in flight, so a transfer that
        # * lands mid-read cannot be undone in the cache.
        return await owner_id_cache.refresh(_OWNER_KEY, _fetch)
    return cast("int | None", await owner_id_cache.get_or_fetch(_OWNER_KEY, _fetch))


async def is_owner(user_id: int, *, fresh: bool = False) -> bool:
    """Return True if user_id belongs to the bot owner.

    Served from the cached owner ID (300 s L1 TTL, invalidated on
    transfer) instead of a dedicated row read so hot auth paths pay
    zero database round trips on cache hits. Errors propagate like the
    previous direct read so decorators keep their fail-closed retry reply.

    With ``fresh=True`` the owner row is read directly from the
    assignments table (mirroring ``get_owner_id(fresh=True)``) so an
    ownership transfer in another process is never hidden for up to the
    300 s owner TTL. Enforcement gates use it; display reads keep the
    cached fast path.
    """
    return (await get_owner_id(fresh=fresh)) == user_id


async def ensure_initial_owner(initial_id: int) -> None:
    """Create the first owner assignment if the community has no owner."""
    if await _owner_count() > 0:
        return

    async def _work(sess: AsyncSession) -> None:
        # * The assignment refers to the identity of the founder, so the
        # * identity row has to exist before the assignment can point at
        # * it. A founder the bot has never seen still owns the community.
        await sess.execute(
            pg_insert(telegram_users)
            .values(user_id=initial_id, created_at=utc_now(), updated_at=utc_now())
            .on_conflict_do_nothing(index_elements=["user_id"])
        )
        await sess.execute(
            pg_insert(role_assignments)
            .values(
                user_id=initial_id,
                role_key=_OWNER_ROLE,
                status="active",
                assigned_at=utc_now(),
            )
            .on_conflict_do_nothing(index_elements=["id"])
        )

    try:
        await run_transaction(_work)
        owner_id_cache.put(_OWNER_KEY, initial_id)
    except Exception:
        # * Another instance won the startup race; drop the cache so the
        # * next read refreshes it.
        owner_id_cache.invalidate(_OWNER_KEY)


async def set_owner(user_id: int) -> None:
    """Replace the current owner with user_id; clears the role cache."""

    # * The transfer runs in one transaction: the new assignment and the
    # * revocation of the old one commit together, so a crash between
    # * them cannot leave two owners or none.
    # * The advisory lock serialises concurrent transfers. Without it two
    # * transfers interleave and the table ends up with no owner row at
    # * all, which would leave the whole community without an owner until
    # * the next restart.
    async def _work(sess: AsyncSession) -> None:
        await sess.execute(
            text("SELECT pg_advisory_xact_lock(:key)"),
            {"key": _OWNER_TRANSFER_LOCK_KEY},
        )
        # * A user holds one active role, so every active assignment of
        # * the new owner is revoked before the owner row is written. A
        # * target that still held the admin role would otherwise make
        # * the insert fail and roll the whole transfer back.
        await sess.execute(
            role_assignments.update()
            .where(
                role_assignments.c.user_id == user_id,
                role_assignments.c.status == "active",
            )
            .values(status="revoked", revoked_at=utc_now())
        )
        await sess.execute(
            role_assignments.update()
            .where(
                role_assignments.c.role_key == _OWNER_ROLE,
                role_assignments.c.status == "active",
            )
            .values(status="revoked", revoked_at=utc_now())
        )
        await sess.execute(
            pg_insert(telegram_users)
            .values(user_id=user_id, created_at=utc_now(), updated_at=utc_now())
            .on_conflict_do_nothing(index_elements=["user_id"])
        )
        await sess.execute(
            pg_insert(role_assignments)
            .values(
                user_id=user_id,
                role_key=_OWNER_ROLE,
                status="active",
                assigned_at=utc_now(),
            )
            .on_conflict_do_nothing(index_elements=["id"])
        )

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
            "the previous owner keeps the role. Inspect the role_assignments "
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
    # * the "role" prefix so no process reads a stale "owner" role after the
    # * transfer completes.
    await effective_role_cache.clear_all()


# ───────────────────────── Admin CRUD ────────────────────────── #


async def is_admin(user_id: int) -> bool:
    """Return True if user_id is a registered admin."""
    row = await db_call(
        lambda: fetch_one(
            select(role_assignments.c.user_id).where(
                role_assignments.c.user_id == user_id,
                role_assignments.c.role_key == _ADMIN_ROLE,
                *_active_assignment(),
            )
        )
    )
    return row is not None


async def add_admin(user_id: int, promoted_by: int) -> None:
    """Give the admin role to a user; no-op if the role is already held."""
    await _assign_role(user_id, _ADMIN_ROLE, promoted_by)
    effective_role_cache.invalidate(user_id)


async def all_admins() -> list[AdminDoc]:
    """Return all admin documents."""
    rows = await db_call(
        lambda: fetch_all(
            select(
                role_assignments.c.user_id,
                role_assignments.c.role_key,
                role_assignments.c.assigned_by_user_id,
                role_assignments.c.assigned_at,
            ).where(
                role_assignments.c.role_key == _ADMIN_ROLE,
                *_active_assignment(),
            )
        )
    )
    return cast("list[AdminDoc]", rows)


async def admin_count() -> int:
    """Return the total count of registered admins."""
    return await _count(
        select(func.count())
        .select_from(role_assignments)
        .where(role_assignments.c.role_key == _ADMIN_ROLE, *_active_assignment())
    )


# ────────────────────────── Role CRUD ─────────────────────────── #


async def set_role(user_id: int, role: str, assigned_by: int) -> None:
    """Assign a community role (developer/tester) to a user."""
    # ! CRITICAL: reject anything outside VALID_ROLES. get_effective_role
    # ! returns the stored value verbatim, so a stored "admin" or "founder"
    # ! would grant real privilege to a role row.
    if role not in VALID_ROLES:
        raise ValueError(f"Refusing to store invalid custom role: {role!r}")
    await _assign_role(user_id, ROLE_KEY_BY_APP_ROLE[role], assigned_by)
    effective_role_cache.invalidate(user_id)


async def remove_role(user_id: int) -> bool:
    """Revoke a user's role; the assignment history stays readable."""
    revoked = await _revoke_role(user_id, None)
    effective_role_cache.invalidate(user_id)
    return revoked


async def get_role(user_id: int) -> str | None:
    """Return the role the user currently holds."""
    row = await db_call(
        lambda: fetch_one(
            select(role_assignments.c.role_key).where(
                role_assignments.c.user_id == user_id,
                *_active_assignment(),
            )
        )
    )
    if row is None:
        return None
    return APP_ROLE_BY_ROLE_KEY.get(str(row["role_key"]))


async def all_by_role(role: str) -> list[RoleRefDoc]:
    """Get all users with a specific role."""
    rows = await db_call(
        lambda: fetch_all(
            select(role_assignments.c.user_id).where(
                role_assignments.c.role_key == ROLE_KEY_BY_APP_ROLE.get(role, role),
                *_active_assignment(),
            )
        )
    )
    return cast("list[RoleRefDoc]", rows)


async def role_count(role: str) -> int:
    """Count role members (count-only views; avoids fetching documents)."""
    return await _count(
        select(func.count())
        .select_from(role_assignments)
        .where(
            role_assignments.c.role_key == ROLE_KEY_BY_APP_ROLE.get(role, role),
            *_active_assignment(),
        )
    )


async def _assign_role(user_id: int, role: str, assigned_by: int) -> None:
    """Give one role to one user and revoke the role it replaces.

    The revocation and the assignment land in one transaction, so a user
    never holds two active roles and the database guard sees a single
    change.
    """

    async def _work(sess: AsyncSession) -> None:
        await sess.execute(
            role_assignments.update()
            .where(
                role_assignments.c.user_id == user_id,
                role_assignments.c.status == "active",
            )
            .values(
                status="revoked", revoked_at=utc_now(), revoked_by_user_id=assigned_by
            )
        )
        await sess.execute(
            pg_insert(role_assignments)
            .values(
                user_id=user_id,
                role_key=role,
                assigned_by_user_id=assigned_by,
                assigned_at=utc_now(),
                status="active",
            )
            .on_conflict_do_nothing(index_elements=["id"])
        )

    await run_transaction(_work)


async def _revoke_role(user_id: int, role: str | None) -> bool:
    """Revoke the active assignment of one user, optionally one role."""
    stmt = role_assignments.update().where(
        role_assignments.c.user_id == user_id,
        role_assignments.c.status == "active",
    )
    if role is not None:
        stmt = stmt.where(role_assignments.c.role_key == role)
    revoked = await db_call(
        lambda: run(stmt.values(status="revoked", revoked_at=utc_now()))
    )
    return revoked > 0


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
    """Resolve the role the user currently holds (L1->L2->DB cached).

    With ``fresh=True`` the effective-role and owner caches are bypassed
    and the assignment is read directly from the database, then the
    effective-role cache is refreshed with the result. Enforcement gates
    (decorators, re-checks, demote repair, threshold ban exemption, appeal
    decisions) use ``fresh=True`` so a demotion in another process is never
    hidden for up to the 60 s role TTL; display reads keep the cached path.
    """

    async def _resolve() -> str | None:
        # * Propagate DB errors so get_or_fetch does not cache a degraded role
        # * result. A false "owner" cached for a real error would silently
        # * bypass authorization checks for every subsequent call until TTL
        # * expiry.
        row = await db_call(
            lambda: fetch_one(
                select(role_assignments.c.role_key).where(
                    role_assignments.c.user_id == user_id,
                    *_active_assignment(),
                )
            )
        )
        role = row["role_key"] if row else None
        if role is not None and role not in APP_ROLE_BY_ROLE_KEY:
            # ! CRITICAL: the assignment table only stores known roles, but
            # ! a hand-edited row could still carry something unexpected.
            # ! Returning it verbatim would grant real privilege, so treat
            # ! unknown stored values as no role instead of trusting the
            # ! document.
            log.error("Ignoring invalid stored role %r for user %d", role, user_id)
            role = None
        return APP_ROLE_BY_ROLE_KEY.get(str(role)) if role is not None else None

    if fresh:
        # * The refresh publishes the value only when the key was not
        # * invalidated while the read was in flight. A demotion that
        # * lands mid-read must not be undone by the stale role the read
        # * carries, or the revoked role keeps serving until the TTL.
        return await effective_role_cache.refresh(user_id, _resolve)
    return cast(
        "str | None", await effective_role_cache.get_or_fetch(user_id, _resolve)
    )


async def role_meta(user_id: int) -> tuple[str | None, int | None, datetime | None]:
    """Return ``(role, assigned_by, assigned_at)`` for the active assignment."""
    row = await db_call(
        lambda: fetch_one(
            select(
                role_assignments.c.role_key,
                role_assignments.c.assigned_by_user_id,
                role_assignments.c.assigned_at,
            ).where(
                role_assignments.c.user_id == user_id,
                *_active_assignment(),
            )
        )
    )
    if not row:
        return None, None, None
    role = APP_ROLE_BY_ROLE_KEY.get(str(row["role_key"]))
    return role, row.get("assigned_by_user_id"), row.get("assigned_at")


# ───────────────────────── Permissions ─────────────────────────── #


async def has_permission(user_id: int, permission_key: str) -> bool:
    """Return True when the user holds the exact permission.

    The check runs in the database: it reads the active assignment and
    walks down to the permission list. It returns false when there is no
    assignment, when the assignment expired, and when the permission is
    unknown, so a failure never grants privilege.
    """
    row = await db_call(
        lambda: fetch_value(select(func.actor_has_permission(user_id, permission_key)))
    )
    return bool(row)


async def permissions_for(user_id: int) -> list[str]:
    """Return the permission keys the user currently holds."""
    rows = await db_call(
        lambda: fetch_all(
            select(role_permissions.c.permission_key)
            .join(
                role_assignments,
                role_assignments.c.role_key == role_permissions.c.role_key,
            )
            .where(
                role_assignments.c.user_id == user_id,
                *_active_assignment(),
            )
            .order_by(role_permissions.c.permission_key)
        )
    )
    return [str(row["permission_key"]) for row in rows]


async def permission_catalog() -> list[dict[str, object]]:
    """Return the permission catalog with the resource of every entry."""
    return await db_call(
        lambda: fetch_all(
            select(
                permission_definitions.c.permission_key,
                permission_definitions.c.resource,
                permission_definitions.c.description,
            ).order_by(permission_definitions.c.permission_key)
        )
    )


async def role_catalog() -> list[dict[str, object]]:
    """Return the role catalog with the priority of every role."""
    return await db_call(
        lambda: fetch_all(
            select(
                role_definitions.c.role_key,
                role_definitions.c.display_name,
                role_definitions.c.priority,
            ).order_by(role_definitions.c.priority.desc())
        )
    )


# * The document shape of an active role assignment.
_ROLE_COLUMNS = (
    role_assignments.c.user_id,
    role_assignments.c.role_key,
    role_assignments.c.assigned_by_user_id,
    role_assignments.c.assigned_at,
)


async def active_assignments() -> list[RoleDoc]:
    """Return every active role assignment."""
    rows = await db_call(
        lambda: fetch_all(select(*_ROLE_COLUMNS).where(*_active_assignment()))
    )
    return cast("list[RoleDoc]", rows)
