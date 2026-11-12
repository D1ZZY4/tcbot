# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Role persistence adapter for the normalized Transsion Core schema."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, cast

from sqlalchemy import (
    BigInteger,
    Column,
    MetaData,
    Table,
    Text,
    and_,
    func,
    or_,
    select,
    text,
    update,
)
from sqlalchemy.dialects.postgresql import insert as pg_insert

from tcbot import cfg
from tcbot.database.cache.singletons import (
    _OWNER_KEY,
    effective_role_cache,
    owner_id_cache,
)
from tcbot.database.documents import AdminDoc, RoleDoc, RoleName, RoleRefDoc
from tcbot.database.engine import (
    db_call,
    fetch_all,
    fetch_count,
    fetch_one,
    run_transaction,
)
from tcbot.database.types import UserId
from tcbot.utils.logger import get_logger
from tcbot.utils.time_and_date import utc_now

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy.ext.asyncio import AsyncSession

log = get_logger(__name__)

# * These declarations describe only the columns owned by this adapter. The
# * normalized Supabase schema remains the migration source of truth; this
# * metadata is never passed to create_all() or Alembic.
_METADATA = MetaData()
federations = Table(
    "federations",
    _METADATA,
    Column("id", BigInteger),
    Column("slug", Text),
    Column("status", Text),
    schema="public",
)
telegram_users = Table(
    "telegram_users",
    _METADATA,
    Column("user_id", BigInteger),
    Column("is_bot"),
    schema="public",
)
role_definitions = Table(
    "role_definitions",
    _METADATA,
    Column("role_key", Text),
    Column("priority"),
    schema="public",
)
role_assignments = Table(
    "role_assignments",
    _METADATA,
    Column("id", BigInteger),
    Column("federation_id", BigInteger),
    Column("user_id", BigInteger),
    Column("role_key", Text),
    Column("assigned_by_user_id", BigInteger),
    Column("assigned_at"),
    Column("status", Text),
    Column("expires_at"),
    Column("revoked_at"),
    Column("revoked_by_user_id", BigInteger),
    schema="public",
)

_LEGACY_TO_NORMALIZED: dict[str, str] = {
    "founder": "owner",
    "admin": "admin",
    "developer": "developer",
    "tester": "moderator",
}
_NORMALIZED_TO_LEGACY: dict[str, RoleName] = {
    value: cast("RoleName", key) for key, value in _LEGACY_TO_NORMALIZED.items()
}
_CUSTOM_ROLE_KEYS: tuple[str, ...] = ("developer", "moderator")
_ROLE_CACHE_PREFIX: str = f"normalized:{cfg.federation_slug}"
_OWNER_CACHE_KEY: str = f"{_ROLE_CACHE_PREFIX}:{_OWNER_KEY}"


def _role_cache_key(user_id: int) -> str:
    """Return a federation-scoped cache key for one effective role."""
    return f"{_ROLE_CACHE_PREFIX}:{user_id}"


def _active_assignment_clause() -> object:
    """Build the predicate for an active assignment whose expiry has not passed."""
    return and_(
        role_assignments.c.status == "active",
        or_(
            role_assignments.c.expires_at.is_(None),
            role_assignments.c.expires_at > func.now(),
        ),
    )


async def _federation_id() -> int:
    """Resolve the one active federation served by this bot instance."""
    rows = await db_call(
        lambda: fetch_all(
            select(federations.c.id)
            .where(
                federations.c.slug == cfg.federation_slug,
                federations.c.status == "active",
            )
            .limit(2)
        )
    )
    if len(rows) != 1:
        raise RuntimeError(
            "Expected exactly one active federation for slug "
            f"{cfg.federation_slug!r}; found {len(rows)}."
        )
    return int(rows[0]["id"])


async def _ensure_telegram_user(sess: AsyncSession, user_id: int) -> None:
    """Create the minimal Telegram identity required by role foreign keys."""
    if user_id <= 0:
        raise ValueError("Telegram user IDs must be positive integers.")
    await sess.execute(
        pg_insert(telegram_users)
        .values(user_id=user_id, is_bot=False)
        .on_conflict_do_nothing(index_elements=[telegram_users.c.user_id])
    )


async def _insert_assignment(
    sess: AsyncSession,
    *,
    federation_id: int,
    user_id: int,
    role_key: str,
    assigned_by_user_id: int | None,
) -> None:
    """Append an active assignment unless the same active role already exists."""
    values = {
        "federation_id": federation_id,
        "user_id": user_id,
        "role_key": role_key,
        "assigned_by_user_id": assigned_by_user_id,
        "assigned_at": utc_now(),
        "status": "active",
    }
    await sess.execute(
        pg_insert(role_assignments)
        .values(**values)
        .on_conflict_do_nothing(
            index_elements=[
                role_assignments.c.federation_id,
                role_assignments.c.user_id,
                role_assignments.c.role_key,
            ],
            index_where=text("status = 'active'"),
        )
    )


async def _read_owner_id() -> int | None:
    """Read the active owner for the configured federation."""
    row = await db_call(
        lambda: fetch_one(
            select(role_assignments.c.user_id)
            .select_from(
                role_assignments.join(
                    federations,
                    role_assignments.c.federation_id == federations.c.id,
                )
            )
            .where(
                federations.c.slug == cfg.federation_slug,
                federations.c.status == "active",
                role_assignments.c.role_key == "owner",
                _active_assignment_clause(),
            )
            .order_by(role_assignments.c.assigned_at.desc())
            .limit(1)
        )
    )
    return int(row["user_id"]) if row else None


async def get_owner_id(*, fresh: bool = False) -> int | None:
    """Return the cached owner ID, bypassing both cache layers for enforcement."""
    if fresh:
        owner_id = await _read_owner_id()
        owner_id_cache.put(_OWNER_CACHE_KEY, owner_id)
        return owner_id
    return cast(
        "int | None",
        await owner_id_cache.get_or_fetch(_OWNER_CACHE_KEY, _read_owner_id),
    )


async def is_owner(user_id: int, *, fresh: bool = False) -> bool:
    """Return whether user_id currently owns the configured federation."""
    return (await get_owner_id(fresh=fresh)) == user_id


async def _owner_count() -> int:
    """Count non-expired active owner assignments for this federation."""
    return await db_call(
        lambda: fetch_count(
            select(func.count())
            .select_from(
                role_assignments.join(
                    federations,
                    role_assignments.c.federation_id == federations.c.id,
                )
            )
            .where(
                federations.c.slug == cfg.federation_slug,
                federations.c.status == "active",
                role_assignments.c.role_key == "owner",
                _active_assignment_clause(),
            )
        )
    )


async def ensure_initial_owner(initial_id: int) -> None:
    """Create the initial owner only when the federation has no active owner."""
    federation_id = await _federation_id()

    async def _work(sess: AsyncSession) -> None:
        await _ensure_telegram_user(sess, initial_id)
        await sess.execute(
            pg_insert(role_assignments)
            .values(
                federation_id=federation_id,
                user_id=initial_id,
                role_key="owner",
                assigned_by_user_id=None,
                assigned_at=utc_now(),
                status="active",
            )
            .on_conflict_do_nothing(
                index_elements=[role_assignments.c.federation_id],
                index_where=text("role_key = 'owner' AND status = 'active'"),
            )
        )

    await run_transaction(_work)
    await get_owner_id(fresh=True)
    effective_role_cache.invalidate(_role_cache_key(initial_id))


async def set_owner(user_id: int) -> None:
    """Transfer ownership atomically while preserving the old assignment history."""
    federation_id = await _federation_id()

    async def _work(sess: AsyncSession) -> None:
        await sess.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:scope, 0))"),
            {"scope": f"tcbot:owner:{federation_id}"},
        )
        await _ensure_telegram_user(sess, user_id)
        await sess.execute(
            update(role_assignments)
            .where(
                role_assignments.c.federation_id == federation_id,
                role_assignments.c.role_key == "owner",
                role_assignments.c.status == "active",
            )
            .values(
                status="revoked",
                revoked_at=func.now(),
                revoked_by_user_id=None,
            )
        )
        await _insert_assignment(
            sess,
            federation_id=federation_id,
            user_id=user_id,
            role_key="owner",
            assigned_by_user_id=None,
        )

    try:
        await run_transaction(_work)
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception(
            "Normalized owner transfer failed for user %d; the transaction "
            "was rolled back and the previous owner remains active.",
            user_id,
        )
        raise

    owner_id_cache.put(_OWNER_CACHE_KEY, user_id)
    await effective_role_cache.clear_all()
    owner_rows = await _owner_count()
    if owner_rows != 1:
        log.error(
            "Normalized ownership transfer left %d active owner assignments; expected 1.",
            owner_rows,
        )


async def is_admin(user_id: int) -> bool:
    """Return whether user_id has an active Administrator assignment."""
    row = await db_call(
        lambda: fetch_one(
            select(role_assignments.c.id)
            .select_from(
                role_assignments.join(
                    federations,
                    role_assignments.c.federation_id == federations.c.id,
                )
            )
            .where(
                federations.c.slug == cfg.federation_slug,
                federations.c.status == "active",
                role_assignments.c.user_id == user_id,
                role_assignments.c.role_key == "admin",
                _active_assignment_clause(),
            )
            .limit(1)
        )
    )
    return row is not None


async def add_admin(user_id: int, promoted_by: int) -> None:
    """Append an Administrator assignment without rewriting an existing one."""
    federation_id = await _federation_id()

    async def _work(sess: AsyncSession) -> None:
        await _ensure_telegram_user(sess, user_id)
        await _ensure_telegram_user(sess, promoted_by)
        await _insert_assignment(
            sess,
            federation_id=federation_id,
            user_id=user_id,
            role_key="admin",
            assigned_by_user_id=promoted_by,
        )

    await run_transaction(_work)
    effective_role_cache.invalidate(_role_cache_key(user_id))


async def remove_admin(user_id: int) -> bool:
    """Revoke the active Administrator assignment without deleting its history."""
    federation_id = await _federation_id()

    async def _work(sess: AsyncSession) -> bool:
        result = await sess.execute(
            update(role_assignments)
            .where(
                role_assignments.c.federation_id == federation_id,
                role_assignments.c.user_id == user_id,
                role_assignments.c.role_key == "admin",
                role_assignments.c.status == "active",
            )
            .values(status="revoked", revoked_at=func.now(), revoked_by_user_id=None)
            .returning(role_assignments.c.id)
        )
        return result.scalar_one_or_none() is not None

    removed = await run_transaction(_work)
    effective_role_cache.invalidate(_role_cache_key(user_id))
    return removed


async def all_admins() -> list[AdminDoc]:
    """Return every user with an active Administrator assignment."""
    rows = await db_call(
        lambda: fetch_all(
            select(role_assignments.c.user_id)
            .select_from(
                role_assignments.join(
                    federations,
                    role_assignments.c.federation_id == federations.c.id,
                )
            )
            .where(
                federations.c.slug == cfg.federation_slug,
                federations.c.status == "active",
                role_assignments.c.role_key == "admin",
                _active_assignment_clause(),
            )
            .order_by(role_assignments.c.user_id)
        )
    )
    return [{"user_id": UserId(int(row["user_id"]))} for row in rows]


async def admin_count() -> int:
    """Count users with an active Administrator assignment."""
    return await db_call(
        lambda: fetch_count(
            select(func.count())
            .select_from(
                role_assignments.join(
                    federations,
                    role_assignments.c.federation_id == federations.c.id,
                )
            )
            .where(
                federations.c.slug == cfg.federation_slug,
                federations.c.status == "active",
                role_assignments.c.role_key == "admin",
                _active_assignment_clause(),
            )
        )
    )


async def set_role(user_id: int, role: str, assigned_by: int) -> None:
    """Replace a Developer or Tester role by revoking and appending history."""
    if role not in {"developer", "tester"}:
        raise ValueError(f"Refusing to store invalid custom role: {role!r}")
    federation_id = await _federation_id()
    role_key = _LEGACY_TO_NORMALIZED[role]

    async def _work(sess: AsyncSession) -> None:
        await _ensure_telegram_user(sess, user_id)
        await _ensure_telegram_user(sess, assigned_by)
        await sess.execute(
            update(role_assignments)
            .where(
                role_assignments.c.federation_id == federation_id,
                role_assignments.c.user_id == user_id,
                role_assignments.c.role_key.in_(_CUSTOM_ROLE_KEYS),
                role_assignments.c.status == "active",
            )
            .values(
                status="revoked",
                revoked_at=func.now(),
                revoked_by_user_id=assigned_by,
            )
        )
        await _insert_assignment(
            sess,
            federation_id=federation_id,
            user_id=user_id,
            role_key=role_key,
            assigned_by_user_id=assigned_by,
        )

    await run_transaction(_work)
    effective_role_cache.invalidate(_role_cache_key(user_id))


async def remove_role(user_id: int) -> bool:
    """Revoke active Developer or Tester assignments while retaining history."""
    federation_id = await _federation_id()

    async def _work(sess: AsyncSession) -> bool:
        result = await sess.execute(
            update(role_assignments)
            .where(
                role_assignments.c.federation_id == federation_id,
                role_assignments.c.user_id == user_id,
                role_assignments.c.role_key.in_(_CUSTOM_ROLE_KEYS),
                role_assignments.c.status == "active",
            )
            .values(status="revoked", revoked_at=func.now(), revoked_by_user_id=None)
            .returning(role_assignments.c.id)
        )
        return result.scalar_one_or_none() is not None

    removed = await run_transaction(_work)
    effective_role_cache.invalidate(_role_cache_key(user_id))
    return removed


async def get_role(user_id: int) -> str | None:
    """Return the active custom role using the legacy Developer/Tester name."""
    row = await db_call(
        lambda: fetch_one(
            select(role_assignments.c.role_key, role_definitions.c.priority)
            .select_from(
                role_assignments.join(
                    federations,
                    role_assignments.c.federation_id == federations.c.id,
                ).join(
                    role_definitions,
                    role_assignments.c.role_key == role_definitions.c.role_key,
                )
            )
            .where(
                federations.c.slug == cfg.federation_slug,
                federations.c.status == "active",
                role_assignments.c.user_id == user_id,
                role_assignments.c.role_key.in_(_CUSTOM_ROLE_KEYS),
                _active_assignment_clause(),
            )
            .order_by(role_definitions.c.priority.desc())
            .limit(1)
        )
    )
    return _NORMALIZED_TO_LEGACY.get(row["role_key"]) if row else None


async def all_by_role(role: str) -> list[RoleRefDoc]:
    """Return user references for one active Developer or Tester role."""
    role_key = _LEGACY_TO_NORMALIZED.get(role)
    if role_key not in _CUSTOM_ROLE_KEYS:
        return []
    rows = await db_call(
        lambda: fetch_all(
            select(role_assignments.c.user_id)
            .select_from(
                role_assignments.join(
                    federations,
                    role_assignments.c.federation_id == federations.c.id,
                )
            )
            .where(
                federations.c.slug == cfg.federation_slug,
                federations.c.status == "active",
                role_assignments.c.role_key == role_key,
                _active_assignment_clause(),
            )
        )
    )
    return [{"user_id": UserId(int(row["user_id"]))} for row in rows]


async def role_count(role: str) -> int:
    """Count users with one active Developer or Tester role."""
    role_key = _LEGACY_TO_NORMALIZED.get(role)
    if role_key not in _CUSTOM_ROLE_KEYS:
        return 0
    return await db_call(
        lambda: fetch_count(
            select(func.count())
            .select_from(
                role_assignments.join(
                    federations,
                    role_assignments.c.federation_id == federations.c.id,
                )
            )
            .where(
                federations.c.slug == cfg.federation_slug,
                federations.c.status == "active",
                role_assignments.c.role_key == role_key,
                _active_assignment_clause(),
            )
        )
    )


async def get_effective_role(user_id: int, *, fresh: bool = False) -> str | None:
    """Resolve the highest active role while preserving the legacy role names."""
    async def _fetch() -> str | None:
        row = await db_call(
            lambda: fetch_one(
                select(role_assignments.c.role_key)
                .select_from(
                    role_assignments.join(
                        federations,
                        role_assignments.c.federation_id == federations.c.id,
                    ).join(
                        role_definitions,
                        role_assignments.c.role_key == role_definitions.c.role_key,
                    )
                )
                .where(
                    federations.c.slug == cfg.federation_slug,
                    federations.c.status == "active",
                    role_assignments.c.user_id == user_id,
                    role_assignments.c.role_key.in_(
                        tuple(_NORMALIZED_TO_LEGACY)
                    ),
                    _active_assignment_clause(),
                )
                .order_by(
                    role_definitions.c.priority.desc(),
                    role_assignments.c.assigned_at.desc(),
                    role_assignments.c.id.desc(),
                )
                .limit(1)
            )
        )
        return _NORMALIZED_TO_LEGACY.get(row["role_key"]) if row else None

    key = _role_cache_key(user_id)
    if fresh:
        role = await _fetch()
        effective_role_cache.put(key, role)
        return role
    return cast("str | None", await effective_role_cache.get_or_fetch(key, _fetch))


async def role_meta(
    user_id: int,
) -> tuple[str | None, int | None, datetime | None]:
    """Return legacy role metadata, with no metadata for the federation owner."""
    role = await get_effective_role(user_id)
    if role is None or role == "founder":
        return role, None, None
    role_key = _LEGACY_TO_NORMALIZED[role]
    row = await db_call(
        lambda: fetch_one(
            select(
                role_assignments.c.assigned_by_user_id,
                role_assignments.c.assigned_at,
            )
            .select_from(
                role_assignments.join(
                    federations,
                    role_assignments.c.federation_id == federations.c.id,
                )
            )
            .where(
                federations.c.slug == cfg.federation_slug,
                federations.c.status == "active",
                role_assignments.c.user_id == user_id,
                role_assignments.c.role_key == role_key,
                _active_assignment_clause(),
            )
            .order_by(role_assignments.c.assigned_at.desc())
            .limit(1)
        )
    )
    if row is None:
        return role, None, None
    assigned_by = row.get("assigned_by_user_id")
    return role, int(assigned_by) if assigned_by is not None else None, row.get("assigned_at")


