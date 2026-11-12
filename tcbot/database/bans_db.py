# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Bans table helpers - manages all ban-related database operations."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from tcbot.database.base import bans
from tcbot.database.documents import BanDoc
from tcbot.database.engine import (
    constraint_name,
    db_call,
    fetch_all,
    fetch_count,
    fetch_one,
    run,
    run_returning,
)
from tcbot.database.types import make_short_id
from tcbot.utils.logger import get_logger
from tcbot.utils.time_and_date import utc_now

if TYPE_CHECKING:
    from datetime import datetime

log = get_logger(__name__)

# ──────────────────────────── Table ─────────────────────────────── #
# * The surrogate primary key stays out of the returned documents: the
# * helpers expose the federation fields, not the storage identity.
_BAN_COLUMNS = [c for c in bans.c if c.name != "id"]

# * Names of the two unique constraints that can reject an insert.
_CONSTRAINT_BAN_ID: str = "uq_bans_ban_id"
_CONSTRAINT_ACTIVE_USER: str = "uq_bans_active_user"


def make_ban_id() -> str:
    """Generate a unique short ID for a new ban record."""
    return make_short_id()


async def create_ban(
    target_id: int,
    reason: str,
    admin_id: int,
    proof_msg_id: int,
    log_msg_id: int,
    ban_id: str | None = None,
    *,
    until_date: datetime | None = None,
    duration_str: str | None = None,
) -> BanDoc:
    """Create a new ban record in the database."""
    auto_id = ban_id is None
    if auto_id:
        ban_id = make_ban_id()
    values = {
        "ban_id": ban_id,
        "banned_user_id": target_id,
        "reason": reason,
        "admin_user_id": admin_id,
        "proof_message_id": proof_msg_id,
        "log_message_id": log_msg_id,
        "previous_proof_message_id": None,
        "previous_log_message_id": None,
        "timestamp": utc_now(),
        "updated_timestamp": None,
        "until_date": until_date,
        "duration_str": duration_str,
        "is_active": True,
        "update_count": 0,
        "review_message_id": None,
        "review_timestamp": None,
    }

    async def _reuse_existing(error: Exception) -> BanDoc:
        """Return the canonical active ban when this insert lost the race."""
        existing = await get_active_ban(target_id)
        if existing is None:
            raise error
        if not auto_id and str(existing.get("ban_id", "")) == str(ban_id):
            # * The explicit id itself is taken, so the caller must not be
            # * handed a record it cannot reference.
            raise error
        log.warning(
            "Concurrent ban for user %d lost the race; reusing ban %s",
            target_id,
            existing.get("ban_id", ""),
        )
        return cast("BanDoc", existing)

    async def _insert() -> list[dict[str, Any]]:
        return await db_call(
            lambda: run_returning(
                pg_insert(bans).values(**values).returning(*_BAN_COLUMNS)
            )
        )

    try:
        rows = await _insert()
    except Exception as insert_error:
        violated = constraint_name(insert_error)
        if violated == _CONSTRAINT_BAN_ID and auto_id:
            # * The generated id collided with an existing one. The id is
            # * random, so this is vanishingly rare, but it must not fail
            # * the moderation action: the caller never supplied the id,
            # * so it can be swapped for a fresh one and the insert retried.
            ban_id = make_ban_id()
            values["ban_id"] = ban_id
            try:
                rows = await _insert()
            except Exception as retry_error:
                # * The retry can lose a different race: a concurrent ban
                # * for the same target. That case has its own handling, so
                # * the raw integrity error must not surface as a write
                # * failure.
                if constraint_name(retry_error) != _CONSTRAINT_ACTIVE_USER:
                    raise
                return await _reuse_existing(retry_error)
        elif violated != _CONSTRAINT_ACTIVE_USER:
            # * Only the one-active-ban-per-user constraint may lose a
            # * race. Any other integrity error is a real defect and
            # * must not be swallowed here.
            raise
        else:
            # * The unique partial index allows only one active ban per user,
            # * so a concurrent ban for the same target loses the race here.
            # * The existing record is the canonical one: the caller keeps it
            # * and the moderation continues.
            return await _reuse_existing(insert_error)
    # * The stored row is the answer: the database filled the defaults
    # * and the server-side timestamp, so the caller sees exactly what a
    # * later read would return.
    return cast("BanDoc", rows[0])


async def update_ban(
    ban_id: str,
    reason: str,
    admin_id: int,
    new_proof_id: int,
    new_log_id: int = 0,
    old_proof_id: int = 0,
    old_log_id: int = 0,
    *,
    until_date: datetime | None = None,
    duration_str: str | None = None,
) -> BanDoc | None:
    """Update an existing ban record with new information."""
    rows = await db_call(
        lambda: run_returning(
            bans.update()
            .where(bans.c.ban_id == ban_id)
            .values(
                reason=reason,
                admin_user_id=admin_id,
                proof_message_id=new_proof_id,
                log_message_id=new_log_id,
                previous_proof_message_id=old_proof_id,
                previous_log_message_id=old_log_id,
                updated_timestamp=utc_now(),
                until_date=until_date,
                duration_str=duration_str,
                update_count=bans.c.update_count + 1,
            )
            .returning(*_BAN_COLUMNS)
        )
    )
    return cast("BanDoc", rows[0]) if rows else None


async def set_log_message_id(ban_id: str, log_msg_id: int) -> None:
    """Update only the log message ID for an existing ban."""
    await db_call(
        lambda: run(
            bans.update()
            .where(bans.c.ban_id == ban_id)
            .values(log_message_id=log_msg_id)
        )
    )


async def deactivate_all_active_bans(user_id: int) -> int:
    """Deactivate every active ban for a user. Returns the number of bans deactivated.

    Use this in unban and appeal-approve flows to ensure all active bans are
    cleared regardless of how many were created (guarding against duplicate
    active bans that may exist from earlier race conditions or re-ban paths).
    """
    return await db_call(
        lambda: run(
            bans.update()
            .where(bans.c.banned_user_id == user_id, bans.c.is_active.is_(True))
            .values(is_active=False)
        )
    )


async def deactivate_extra_active_bans(user_id: int, keep_ban_id: str) -> int:
    """Deactivate all active bans for a user except the one with keep_ban_id.

    Called during the ban flow when an existing active ban is being updated
    to suppress any stale duplicate active bans while preserving the canonical
    record that is being reused. Returns the number of extras deactivated.
    """
    return await db_call(
        lambda: run(
            bans.update()
            .where(
                bans.c.banned_user_id == user_id,
                bans.c.is_active.is_(True),
                bans.c.ban_id != keep_ban_id,
            )
            .values(is_active=False)
        )
    )


async def set_review_if_absent(ban_id: str, msg_id: int) -> bool:
    """Atomically claim the pending-review slot; return True when claimed.

    The filter matches only when no review is stored, so two concurrent
    appeal submissions for the same ban cannot both claim the slot: the
    loser sees an affected-row count of zero and must discard its orphan
    review card instead of overwriting the winner.
    """
    affected = await db_call(
        lambda: run(
            bans.update()
            .where(bans.c.ban_id == ban_id, bans.c.review_message_id.is_(None))
            .values(review_message_id=msg_id, review_timestamp=utc_now())
        )
    )
    return affected > 0


async def clear_review(ban_id: str) -> None:
    """Clear review_message_id from a ban, allowing a new appeal to be submitted.

    Called after an appeal is rejected so the banned user is not permanently
    locked out from submitting a second appeal.
    """
    await db_call(
        lambda: run(
            bans.update()
            .where(bans.c.ban_id == ban_id)
            .values(review_message_id=None, review_timestamp=None)
        )
    )


async def claim_appeal_decision(ban_id: str, review_msg_id: int) -> bool:
    """Atomically claim one appeal decision; return True when claimed.

    The filter matches only the exact review card the tapper saw while the
    ban is still active. Two concurrent Approve/Reject taps both pass the
    read checks, but only the first update matches: the loser sees an
    affected-row count of zero and must abort instead of double-executing
    (duplicate unbans, contradictory approve+reject, duplicate logs).

    The claim consumes the review slot. A claim that ends without a
    decision must hand the slot back with :func:`restore_review`.
    """
    affected = await db_call(
        lambda: run(
            bans.update()
            .where(
                bans.c.ban_id == ban_id,
                bans.c.is_active.is_(True),
                bans.c.review_message_id == review_msg_id,
            )
            .values(review_message_id=None, review_timestamp=None)
        )
    )
    return affected > 0


async def restore_review(
    ban_id: str,
    review_msg_id: int,
    review_timestamp: datetime | None = None,
) -> bool:
    """Hand a claimed review slot back; return True when it was restored.

    A staff member who cannot decide (a rank refusal, a database outage)
    must not leave the review card dead. The restore only fills an empty
    slot on a ban that is still active and not yet rejected, so it cannot
    resurrect a review that another reviewer already decided.
    """
    affected = await db_call(
        lambda: run(
            bans.update()
            .where(
                bans.c.ban_id == ban_id,
                bans.c.is_active.is_(True),
                bans.c.review_message_id.is_(None),
                bans.c.rejected_at.is_(None),
            )
            .values(
                review_message_id=review_msg_id,
                review_timestamp=review_timestamp or utc_now(),
            )
        )
    )
    return affected > 0


async def set_rejected_by(ban_id: str, admin_id: int, admin_name: str) -> None:
    """Persist the rejector identity and rejection timestamp on a ban document.

    Called on appeal reject so the audit trail is preserved even if the log
    message is later deleted or the log channel is unavailable.
    """
    await db_call(
        lambda: run(
            bans.update()
            .where(bans.c.ban_id == ban_id)
            .values(
                rejected_by_id=admin_id,
                rejected_by_name=admin_name,
                rejected_at=utc_now(),
            )
        )
    )


async def set_appeal_log_msg(
    ban_id: str,
    msg_id: int,
    submitted_at: datetime | None = None,
    appeal_link: str = "",
) -> None:
    """Attach appeal-related metadata to a ban record."""
    await db_call(
        lambda: run(
            bans.update()
            .where(bans.c.ban_id == ban_id)
            .values(
                appeal_log_msg_id=msg_id,
                appeal_submitted_at=submitted_at or utc_now(),
                appeal_link=appeal_link,
            )
        )
    )


# ─────────────────────────── Queries ─────────────────────────── #


async def get_active_ban(user_id: int) -> BanDoc | None:
    """Get the currently active ban for a specific user."""
    return cast(
        "BanDoc | None",
        await db_call(
            lambda: fetch_one(
                select(*_BAN_COLUMNS)
                .where(bans.c.banned_user_id == user_id, bans.c.is_active.is_(True))
                .order_by(bans.c.timestamp.desc(), bans.c.ban_id.desc())
            )
        ),
    )


async def get_ban(ban_id: str) -> BanDoc | None:
    """Get any ban record by its unique ban_id."""
    return cast(
        "BanDoc | None",
        await db_call(
            lambda: fetch_one(select(*_BAN_COLUMNS).where(bans.c.ban_id == ban_id))
        ),
    )


async def active_ban_count() -> int:
    """Count the total number of currently active bans."""
    return await db_call(
        lambda: fetch_count(
            select(func.count()).select_from(bans).where(bans.c.is_active.is_(True))
        )
    )


async def active_bans_page(skip: int, limit: int) -> list[BanDoc]:
    """Return one page of active bans, newest first (server-side skip/limit).

    Only the visible slice travels over the wire regardless of federation
    size. Uses the ``(is_active, timestamp, ban_id)`` index.
    """
    # * Clamp once so cursor limit and fetch length can never disagree;
    # * callers always pass positive values, this only pins the edge.
    page_size = max(1, limit)
    return cast(
        "list[BanDoc]",
        await db_call(
            lambda: fetch_all(
                select(*_BAN_COLUMNS)
                .where(bans.c.is_active.is_(True))
                .order_by(bans.c.timestamp.desc(), bans.c.ban_id.desc())
                .offset(max(0, skip))
                .limit(page_size)
            )
        ),
    )


async def active_bans_for_users(user_ids: list[int]) -> list[BanDoc]:
    """Return active bans for the given users (server-side ``IN``).

    Backs name-search results without loading the whole active-ban list.
    Uses the ``(banned_user_id, is_active, ...)`` index.
    """
    if not user_ids:
        return []
    return cast(
        "list[BanDoc]",
        await db_call(
            lambda: fetch_all(
                select(*_BAN_COLUMNS)
                .where(bans.c.banned_user_id.in_(user_ids), bans.c.is_active.is_(True))
                .order_by(bans.c.timestamp.desc(), bans.c.ban_id.desc())
            )
        ),
    )


async def user_appealable_bans(
    user_id: int, *, skip: int = 0, limit: int | None = None
) -> list[BanDoc]:
    """Return the user's bans that ever had an appeal submitted, newest first.

    Server-side version of the "appeal was submitted" filter; same
    predicate as :func:`user_appeal_count`, served by the partial
    ``(banned_user_id, appeal_log_msg_id)`` index. ``limit=None`` returns
    the full list.
    """
    stmt = (
        select(*_BAN_COLUMNS)
        .where(
            bans.c.banned_user_id == user_id,
            bans.c.appeal_log_msg_id.isnot(None),
        )
        .order_by(bans.c.timestamp.desc(), bans.c.ban_id.desc())
        .offset(max(0, skip))
    )
    if limit is not None:
        stmt = stmt.limit(max(1, limit))
    return cast("list[BanDoc]", await db_call(lambda: fetch_all(stmt)))


async def active_ban_user_ids() -> list[int]:
    """Return only the user IDs of all active bans (projection-only, fastest path).

    Uses ``DISTINCT`` so the full ban documents never travel, and duplicate
    active rows for one user collapse to a single ID for the fan-out.
    """
    rows = await db_call(
        lambda: fetch_all(
            select(bans.c.banned_user_id).where(bans.c.is_active.is_(True)).distinct()
        )
    )
    return [int(row["banned_user_id"]) for row in rows]


async def user_bans(
    user_id: int, *, skip: int = 0, limit: int | None = None
) -> list[BanDoc]:
    """Return every ban (active + inactive) for a user, newest first.

    ``limit=None`` returns the full list (backwards compatible).
    """
    stmt = (
        select(*_BAN_COLUMNS)
        .where(bans.c.banned_user_id == user_id)
        .order_by(bans.c.timestamp.desc(), bans.c.ban_id.desc())
        .offset(max(0, skip))
    )
    if limit is not None:
        stmt = stmt.limit(max(1, limit))
    return cast("list[BanDoc]", await db_call(lambda: fetch_all(stmt)))


async def user_ban_count(user_id: int) -> int:
    """Count every ban ever issued against the user."""
    return await db_call(
        lambda: fetch_count(
            select(func.count())
            .select_from(bans)
            .where(bans.c.banned_user_id == user_id)
        )
    )


async def user_appeal_count(user_id: int) -> int:
    """Count bans on this user that ever had an appeal submitted."""
    return await db_call(
        lambda: fetch_count(
            select(func.count())
            .select_from(bans)
            .where(
                bans.c.banned_user_id == user_id,
                bans.c.appeal_log_msg_id.isnot(None),
            )
        )
    )
