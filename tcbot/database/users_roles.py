# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Staff role helpers over the role assignment table."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, Literal, cast

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import CursorResult

from tcbot.database.base import (
    permission_definitions,
    role_assignments,
    role_definitions,
    role_permissions,
    telegram_users,
)
from tcbot.database.cache import effective_role_cache, owner_id_cache
from tcbot.database.cache.singletons import _OWNER_KEY
from tcbot.database.documents import AdminDoc, RoleRefDoc
from tcbot.database.engine import (
    db_call,
    fetch_all,
    fetch_one,
    fetch_value,
    run,
    run_transaction,
)
from tcbot.database.users_cache import ensure_users
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

VALID_ROLES: tuple[Literal["developer", "moderator"], ...] = (
    "developer",
    "moderator",
)

# * Name of a community role. The role argument of every permission gate
# * is typed with it, so a typo in a threshold name is a type error the
# * checker reports instead of a rank that silently matches nobody.
RoleName = Literal["owner", "admin", "developer", "moderator"]

# * Spellings the promote command accepts for a role. The table is role
# * vocabulary, so it belongs next to the other role tables rather than
# * in a command module.
ROLE_ALIASES: dict[str, str] = {
    "admin": "admin",
    "developer": "developer",
    "dev": "developer",
    "moderator": "moderator",
    "mod": "moderator",
}

ROLE_RANK: dict[str, int] = {
    "owner": 4,
    "admin": 3,
    "developer": 2,
    "moderator": 1,
}

ROLE_LABEL: dict[str, str] = {
    "owner": "Owner",
    "admin": "Admin",
    "developer": "Developer",
    "moderator": "Moderator",
}

# * Single owner for the two role sets the moderation paths test against.
# * Open-coding them per call site let a new tier land in ROLE_RANK and be
# * missed by every set check, so the rank gate and the staff gate would
# * disagree about the same user.
# * STAFF_ROLES holds every role that can be demoted (the owner is protected
# * and never demoted); OWNER_ADMIN_ROLES holds the roles that count as
# * community staff for permission gates.
STAFF_ROLES: frozenset[str] = frozenset({"admin", "developer", "moderator"})
OWNER_ADMIN_ROLES: frozenset[str] = frozenset({"owner", "admin"})

# * The application and the database use the same four role names. The
# * translation tables the old vocabulary needed are gone, so a stored
# * role key reaches the checks unchanged.
_OWNER_ROLE: str = "owner"
_ADMIN_ROLE: str = "admin"


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


async def _fetch_owner_id() -> int | None:
    """Read the current owner from the assignments table.

    Shared by the cached getter and the post-transfer publisher so both
    publish a value read from the source under the same generation guard.
    """
    # * The lowest owner row wins, exactly like the old sorted read.
    row = await db_call(
        lambda: fetch_one(
            select(role_assignments.c.user_id)
            .where(role_assignments.c.role_key == _OWNER_ROLE, *_active_assignment())
            .order_by(role_assignments.c.user_id)
            .limit(1)
        )
    )
    return row["user_id"] if row else None


async def get_owner_id(*, fresh: bool = False) -> int | None:
    """Return the current owner's user ID (L1->L2->DB cached).

    With ``fresh=True`` the cache is bypassed and the row is read directly
    from the assignments table, then the cache is refreshed. Enforcement
    decisions use ``fresh=True`` so a transfer in another process is never
    hidden for up to the 300 s owner TTL; display reads keep the cached
    fast path.
    """
    if fresh:
        # * The refresh publishes the value only when the key was not
        # * invalidated while the read was in flight, so a transfer that
        # * lands mid-read cannot be undone in the cache.
        return await owner_id_cache.refresh(_OWNER_KEY, _fetch_owner_id)
    return cast(
        "int | None", await owner_id_cache.get_or_fetch(_OWNER_KEY, _fetch_owner_id)
    )


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
    """Create the first owner assignment if the community has no owner.

    The seed runs under the ownership-transfer lock and re-checks the table
    inside it, so two instances starting together cannot both write an owner.
    The configured owner may already hold a lower role on a restored
    database; that assignment is revoked in the same transaction, because a
    user holds one active role. A seed that still fails is logged once the
    table is re-read, so a community left without an owner is visible instead
    of silently inaccessible.
    """
    if await _owner_count() > 0:
        return

    async def _work(sess: AsyncSession) -> int:
        await sess.execute(
            text("SELECT pg_advisory_xact_lock(:key)"),
            {"key": _OWNER_TRANSFER_LOCK_KEY},
        )
        existing_owner = await sess.scalar(
            select(role_assignments.c.user_id)
            .where(role_assignments.c.role_key == _OWNER_ROLE, *_active_assignment())
            .order_by(role_assignments.c.user_id)
            .limit(1)
        )
        if existing_owner is not None:
            return int(existing_owner)
        # * The configured owner may already hold a lower role on a
        # * restored database, and the one-active-role index would refuse
        # * the owner insert. The owner role replaces it, exactly like an
        # * ownership transfer does.
        await sess.execute(
            role_assignments.update()
            .where(
                role_assignments.c.user_id == initial_id,
                role_assignments.c.status == "active",
            )
            .values(status="revoked", revoked_at=utc_now())
        )
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
            .on_conflict_do_nothing()
        )
        return initial_id

    try:
        owner_id = await run_transaction(_work)
    except Exception:
        # * Another instance may have completed the seed between the check
        # * above and this transaction. Re-read the table: only a community
        # * that still has no owner is a real failure.
        owner_id_cache.invalidate(_OWNER_KEY)
        try:
            owner_id = await get_owner_id(fresh=True)
        except Exception:
            owner_id = None
        if owner_id is None:
            log.exception(
                "Initial owner seed failed for %d and no active owner exists",
                initial_id,
            )
        return
    owner_id_cache.put(_OWNER_KEY, owner_id)
    # * The seed may have replaced a lower role of the configured owner, so
    # * a cached effective role for that user is stale.
    effective_role_cache.invalidate(initial_id)


async def set_owner(user_id: int) -> None:
    """Replace the current owner with user_id; clears the role cache.

    Low-level assignment primitive for seeding and invariant tests. The
    ownership command must use :func:`transfer_ownership`, which also grants
    the previous Owner the Admin role in the same transaction. Calling
    this helper directly would leave the previous Owner without a role.
    """

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
            pg_insert(role_assignments).values(
                user_id=user_id,
                role_key=_OWNER_ROLE,
                status="active",
                assigned_at=utc_now(),
            )
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
    await _publish_owner(user_id, action="set_owner")


async def _publish_owner(user_id: int, *, action: str) -> None:
    """Refresh the caches and verify the single-owner invariant after a swap."""
    # * A guarded refresh, not a blind put: two overlapping transfers commit
    # * in lock order but can publish out of order after the lock is released.
    # * The generation guard discards a read that overlapped another write.
    try:
        await owner_id_cache.refresh(_OWNER_KEY, _fetch_owner_id)
    except asyncio.CancelledError:
        raise
    except Exception:
        # * The swap is already committed. Invalidate instead of failing the
        # * command, so the next display read re-reads the source.
        log.exception("%s owner cache refresh failed for user %d", action, user_id)
        owner_id_cache.invalidate(_OWNER_KEY)
    # * The transaction is atomic, so the invariant holds. Verify it anyway
    # * and log loudly, so a split brain is noticed instead of serving
    # * nondeterministic owners.
    try:
        owner_rows = await _owner_count()
    except Exception:
        log.exception("%s verification read failed for user %d", action, user_id)
    else:
        if owner_rows != 1:
            log.error(
                "%s left %d owner rows for user %d; expected exactly 1.",
                action,
                owner_rows,
                user_id,
            )
    # * Full two-layer invalidation: the previous owner's ID may be unknown
    # * to a caller, so clear_all() sweeps L1 and every Redis key under the
    # * "role" prefix. No process can read a stale "owner" role afterwards.
    await effective_role_cache.clear_all()


async def transfer_ownership(previous_owner_id: int, new_owner_id: int) -> None:
    """Move ownership and keep the previous Owner as Admin in one transaction.

    The owner swap and the previous Owner's Admin assignment have to land
    together. A former split committed the swap first and granted the Admin
    role second, so a failure in the second write left the former Owner
    with no role at all. The current owner is verified under the transfer
    lock, so a stale transfer prompt cannot demote the wrong account.
    """
    if previous_owner_id == new_owner_id:
        raise ValueError("A transfer target must differ from the current owner")

    async def _work(sess: AsyncSession) -> None:
        await sess.execute(
            text("SELECT pg_advisory_xact_lock(:key)"),
            {"key": _OWNER_TRANSFER_LOCK_KEY},
        )
        current_owner = await sess.scalar(
            select(role_assignments.c.user_id).where(
                role_assignments.c.role_key == _OWNER_ROLE,
                role_assignments.c.status == "active",
            )
        )
        if current_owner != previous_owner_id:
            raise RuntimeError(
                "Ownership changed while the transfer prompt was open; "
                "no role was modified"
            )
        await ensure_users(sess, previous_owner_id, new_owner_id)
        # * A user holds one active role, so the new owner's assignments are
        # * revoked before the owner row is written.
        await sess.execute(
            role_assignments.update()
            .where(
                role_assignments.c.user_id == new_owner_id,
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
            pg_insert(role_assignments).values(
                user_id=new_owner_id,
                role_key=_OWNER_ROLE,
                assigned_by_user_id=previous_owner_id,
                assigned_at=utc_now(),
                status="active",
            )
        )
        await sess.execute(
            pg_insert(role_assignments).values(
                user_id=previous_owner_id,
                role_key=_ADMIN_ROLE,
                assigned_by_user_id=previous_owner_id,
                assigned_at=utc_now(),
                status="active",
            )
        )

    try:
        await run_transaction(_work)
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception(
            "transfer_ownership from %d to %d failed; the previous owner keeps "
            "the role",
            previous_owner_id,
            new_owner_id,
        )
        raise
    await _publish_owner(new_owner_id, action="transfer_ownership")
    effective_role_cache.invalidate(previous_owner_id)
    effective_role_cache.invalidate(new_owner_id)


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


async def add_admin(
    user_id: int,
    promoted_by: int,
    *,
    expected_role: str | None = None,
    expect_no_role: bool = False,
) -> None:
    """Give the admin role to a user; no-op if the role is already held."""
    await _assign_role(
        user_id,
        _ADMIN_ROLE,
        promoted_by,
        expected_role=expected_role,
        expect_no_role=expect_no_role,
    )
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


async def set_role(
    user_id: int,
    role: str,
    assigned_by: int,
    *,
    expected_role: str | None = None,
    expect_no_role: bool = False,
) -> None:
    """Assign a community role (developer/moderator) to a user."""
    # ! CRITICAL: reject anything outside VALID_ROLES. get_effective_role
    # ! returns the stored value verbatim, so a stored "admin" or "owner"
    # ! would grant real privilege to a role row.
    if role not in VALID_ROLES:
        raise ValueError(f"Refusing to store invalid custom role: {role!r}")
    await _assign_role(
        user_id,
        role,
        assigned_by,
        expected_role=expected_role,
        expect_no_role=expect_no_role,
    )
    effective_role_cache.invalidate(user_id)


async def change_role(
    user_id: int,
    role: str,
    assigned_by: int,
    *,
    expected_role: str | None = None,
    expect_no_role: bool = False,
) -> None:
    """Replace a staff member's role with another assignable tier.

    ``set_role`` is deliberately limited to Developer/Moderator. This helper
    also allows Admin, so an existing staff member can move between any of the
    three assignable tiers without a remove-then-add gap. The Owner role is
    never touched: ``_assign_role`` refuses to revoke it and the uniqueness
    guard rejects the new assignment, so an Owner target always fails closed.
    """
    if role not in ("admin", "developer", "moderator"):
        raise ValueError(f"Refusing to change to role: {role!r}")
    await _assign_role(
        user_id,
        role,
        assigned_by,
        expected_role=expected_role,
        expect_no_role=expect_no_role,
    )
    effective_role_cache.invalidate(user_id)


async def remove_role(user_id: int, *, expected_role: str | None = None) -> bool:
    """Revoke a user's community role; the assignment history stays readable.

    The owner assignment is never revoked here: ownership changes through
    ``set_owner``, which swaps the owner and its role in one transaction.
    A demote therefore cannot leave the federation without a Owner.

    ``expected_role`` makes the revoke conditional on the role that was
    authorized. A target promoted between the authorization read and this
    write keeps the new role instead of having an Admin assignment stripped
    by a decision that only permitted a Moderator demotion.
    """
    revoked = await _revoke_role(user_id, expected_role)
    effective_role_cache.invalidate(user_id)
    return revoked


async def all_by_role(role: str) -> list[RoleRefDoc]:
    """Get all users with a specific role."""
    rows = await db_call(
        lambda: fetch_all(
            select(role_assignments.c.user_id).where(
                role_assignments.c.role_key == role,
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
            role_assignments.c.role_key == role,
            *_active_assignment(),
        )
    )


async def _assign_role(
    user_id: int,
    role: str,
    assigned_by: int,
    *,
    expected_role: str | None = None,
    expect_no_role: bool = False,
) -> None:
    """Give one role to one user and revoke the role it replaces.

    The revocation and the assignment land in one transaction, so a user
    never holds two active roles and the database guard sees a single
    change.
    """

    async def _work(sess: AsyncSession) -> None:
        # * The assignment references both accounts. A target the member
        # * cache has never seen must not fail the promotion on a foreign key.
        await ensure_users(sess, user_id, assigned_by)
        # ! CRITICAL: never revoke the owner assignment here. Only
        # ! set_owner replaces the Owner; a grant that targeted the owner
        # ! must fail the active-user uniqueness rule instead of leaving the
        # ! community without an owner.
        if not expect_no_role:
            revoke = (
                role_assignments.update()
                .where(
                    role_assignments.c.user_id == user_id,
                    role_assignments.c.status == "active",
                    role_assignments.c.role_key != _OWNER_ROLE,
                )
                .values(
                    status="revoked",
                    revoked_at=utc_now(),
                    revoked_by_user_id=assigned_by,
                )
            )
            if expected_role is not None:
                # ! CRITICAL: only revoke the tier that was authorized. A
                # ! target promoted while the ban or rank read was in flight
                # ! must keep the new role instead of being demoted by a
                # ! stale grant decision.
                revoke = revoke.where(role_assignments.c.role_key == expected_role)
            result = cast("CursorResult[Any]", await sess.execute(revoke))
            if expected_role is not None and result.rowcount != 1:
                raise ValueError(
                    f"expected role {expected_role!r} changed before the grant"
                )
        # * With expect_no_role there is nothing to revoke. The partial unique
        # * index on active assignments rejects a concurrent grant instead of
        # * letting this decision strip a role that appeared after the read.
        await sess.execute(
            pg_insert(role_assignments).values(
                user_id=user_id,
                role_key=role,
                assigned_by_user_id=assigned_by,
                assigned_at=utc_now(),
                status="active",
            )
        )

    await run_transaction(_work)


async def _revoke_role(user_id: int, role: str | None) -> bool:
    """Revoke the active assignment of one user, optionally one role.

    The owner assignment is excluded, so a demote path can never strip the
    Owner role; only :func:`set_owner` replaces it.
    """
    stmt = role_assignments.update().where(
        role_assignments.c.user_id == user_id,
        role_assignments.c.status == "active",
        role_assignments.c.role_key != _OWNER_ROLE,
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
    return role in OWNER_ADMIN_ROLES


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
        if role is not None and role not in ROLE_RANK:
            # ! CRITICAL: the assignment table only stores known roles, but
            # ! a hand-edited row could still carry something unexpected.
            # ! Returning it verbatim would grant real privilege, so treat
            # ! unknown stored values as no role instead of trusting the
            # ! document.
            log.error("Ignoring invalid stored role %r for user %d", role, user_id)
            return None
        return str(role) if role is not None else None

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
    role = str(row["role_key"]) if row["role_key"] in ROLE_RANK else None
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
