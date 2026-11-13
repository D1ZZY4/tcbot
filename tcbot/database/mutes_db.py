# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Community mute helpers over the moderation decision tables.

A mute is one decision in ``moderation_actions``. The live state and the
history are the same row: an active mute is a decision whose status is
``active``, and lifting it moves the row to ``revoked``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from tcbot.database.base import moderation_actions, moderation_cases
from tcbot.database.documents import ActiveMuteDoc, MuteDoc
from tcbot.database.engine import (
    constraint_name,
    db_call,
    fetch_all,
    fetch_one,
    fetch_value,
    run,
    run_transaction,
)
from tcbot.database.types import ChatId, UserId
from tcbot.utils.logger import get_logger
from tcbot.utils.time_and_date import utc_now

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy.ext.asyncio import AsyncSession

log = get_logger(__name__)

# ──────────────────────────── Tables ────────────────────────────── #
# * The surrogate primary key stays out of the returned documents: the
# * helpers expose the community fields, not the storage identity.
_MUTE_COLUMNS = (
    moderation_actions.c.id,
    moderation_actions.c.external_ref,
    moderation_actions.c.target_user_id,
    moderation_actions.c.actor_user_id,
    moderation_actions.c.reason,
    moderation_actions.c.duration_seconds,
    moderation_actions.c.created_at,
    moderation_actions.c.expires_at,
    moderation_actions.c.status,
    moderation_actions.c.case_id,
    moderation_actions.c.origin_chat_id,
    moderation_actions.c.metadata,
)

# * The live mute row is keyed by the muted user, so the whole row is
# * the document: there is no surrogate id to hide.

# * Name of the partial unique index that keeps one active mute per
# * target. A second decision has to supersede the first one.
_CONSTRAINT_ACTIVE_MUTE: str = "uq_moderation_actions_active_mute"


# ──────────────────────────── Mutations ─────────────────────────── #
# * Functions that create or modify mute decisions.
# * Primarily used for audit logging of moderation actions.


async def record_mute(
    user_id: int,
    chat_id: int,
    reason: str,
    admin_id: int,
    *,
    until: datetime | None = None,
) -> int:
    """Record a community mute and return the decision id.

    The deadline is stored as an absolute expiry, and the duration the
    decision shows is derived from it, so the two can never disagree. A
    permanent mute has no expiry and no duration.

    The decision and the case that holds it land in one transaction, so a
    mute without an investigation cannot exist.

    A second mute of a user who is already muted is a new decision that
    supersedes the old one: the history keeps the first mute and its
    reason, and only the newest decision is in force. The stored deadline
    never moves backwards, so a timed mute cannot shorten a longer
    restriction and a permanent mute is never downgraded to a timed one.
    """

    async def _work(sess: AsyncSession) -> int:
        case_id = await _open_case(sess, user_id, admin_id, reason)
        previous = (
            (
                await sess.execute(
                    select(
                        moderation_actions.c.id,
                        moderation_actions.c.expires_at,
                    ).where(
                        moderation_actions.c.target_user_id == user_id,
                        moderation_actions.c.action_type == "mute",
                        moderation_actions.c.status == "active",
                        # * A mute that ran out is not in force any more,
                        # * even before the sweep moves it to its expired
                        # * state. Superseding it would target a row that
                        # * is no longer active and fail the whole write.
                        (moderation_actions.c.expires_at.is_(None))
                        | (moderation_actions.c.expires_at > utc_now()),
                    )
                )
            )
            .mappings()
            .first()
        )
        expires_at = until
        supersedes: int | None = None
        if previous is not None:
            supersedes = int(previous["id"])
            stored = previous["expires_at"]
            if stored is None or until is None:
                # * A permanent mute outranks every deadline: the new
                # * decision carries no expiry, so the restriction never
                # * runs out on its own.
                expires_at = None
            elif until > stored:
                expires_at = until
            else:
                expires_at = stored
        row = (
            (
                await sess.execute(
                    pg_insert(moderation_actions)
                    .values(
                        action_type="mute",
                        scope_type="community",
                        chat_id=None,
                        origin_chat_id=chat_id,
                        target_user_id=user_id,
                        actor_user_id=admin_id,
                        reason=reason,
                        duration_seconds=_duration_seconds(expires_at),
                        created_at=utc_now(),
                        expires_at=expires_at,
                        status="active",
                        case_id=case_id,
                        supersedes_action_id=supersedes,
                        action_origin="manual",
                    )
                    .returning(moderation_actions.c.id)
                )
            )
            .mappings()
            .first()
        )
        if row is None:
            raise RuntimeError("the mute decision was not written")
        return int(row["id"])

    try:
        return await db_call(lambda: run_transaction(_work))
    except Exception as exc:
        if constraint_name(exc) != _CONSTRAINT_ACTIVE_MUTE:
            raise
        # * A concurrent mute won the race and committed its decision
        # * first. The retry reads the mute that is now in force and
        # * supersedes it, so both moderators end up with one mute and a
        # * readable history.
        log.info(
            "Concurrent mute for user %d lost the race; retrying against it.",
            user_id,
        )
        return await db_call(lambda: run_transaction(_work))


def _duration_seconds(until: datetime | None) -> int | None:
    """Return the remaining lifetime of a decision in whole seconds."""
    if until is None:
        return None
    return max(int((until - utc_now()).total_seconds()), 0)


async def _open_case(
    sess: AsyncSession, target_id: int, admin_id: int, reason: str
) -> int:
    """Return the open case of the target, or open one for the decision."""
    existing = (
        (
            await sess.execute(
                select(moderation_cases.c.id)
                .where(
                    moderation_cases.c.subject_user_id == target_id,
                    moderation_cases.c.status.in_(
                        ("open", "collecting_evidence", "under_review")
                    ),
                )
                .order_by(moderation_cases.c.created_at.desc())
                .limit(1)
            )
        )
        .mappings()
        .first()
    )
    if existing is not None:
        return int(existing["id"])

    created = (
        (
            await sess.execute(
                pg_insert(moderation_cases)
                .values(
                    subject_user_id=target_id,
                    case_type="rule_violation",
                    title=f"Community mute of {target_id}",
                    summary=reason,
                    severity="unknown",
                    status="open",
                    source="manual",
                    opened_by_user_id=admin_id,
                    requires_evidence=False,
                )
                .returning(moderation_cases.c.id)
            )
        )
        .mappings()
        .first()
    )
    if created is None:
        raise RuntimeError("the moderation case was not written")
    return int(created["id"])


# ──────────────────────── Active mute store ─────────────────────── #
# * The active mute is the decision whose status is ``active`` and whose
# * expiry has not passed. The decision is written before the restrict
# * fan-out, so no group is touched when the record cannot persist.
# * The expiry is read at query time, so no background cleanup job is
# * needed to keep the view honest.


async def clear_active_mute(user_id: int) -> None:
    """Revoke the active mute of a user when they are unmuted."""
    await db_call(
        lambda: run(
            moderation_actions.update()
            .where(
                moderation_actions.c.target_user_id == user_id,
                moderation_actions.c.action_type == "mute",
                moderation_actions.c.status == "active",
            )
            .values(status="revoked", revoked_at=utc_now())
        )
    )


async def get_active_mute(user_id: int) -> ActiveMuteDoc | None:
    """Return the active mute for a user, or None if none exists or has expired."""
    now = utc_now()
    row = await db_call(
        lambda: fetch_one(
            select(
                moderation_actions.c.target_user_id,
                moderation_actions.c.expires_at,
                moderation_actions.c.created_at,
            ).where(
                moderation_actions.c.target_user_id == UserId(user_id),
                moderation_actions.c.action_type == "mute",
                moderation_actions.c.status == "active",
                (moderation_actions.c.expires_at.is_(None))
                | (moderation_actions.c.expires_at > now),
            )
        )
    )
    if row is None:
        return None
    return ActiveMuteDoc(
        user_id=UserId(int(row["target_user_id"])),
        until_date=row.get("expires_at"),
        timestamp=row["created_at"],
    )


async def active_mute_docs() -> list[ActiveMuteDoc]:
    """Return all currently active mute records (used for group-connect replay).

    Expired timed mutes (``expires_at <= now``) are excluded at query time.
    """
    now = utc_now()
    rows = await db_call(
        lambda: fetch_all(
            select(
                moderation_actions.c.target_user_id,
                moderation_actions.c.expires_at,
                moderation_actions.c.created_at,
            ).where(
                moderation_actions.c.action_type == "mute",
                moderation_actions.c.status == "active",
                (moderation_actions.c.expires_at.is_(None))
                | (moderation_actions.c.expires_at > now),
            )
        )
    )
    return [
        ActiveMuteDoc(
            user_id=UserId(int(row["target_user_id"])),
            until_date=row.get("expires_at"),
            timestamp=row["created_at"],
        )
        for row in rows
    ]


# ─────────────────────── Per-user history ───────────────────────── #


async def user_mutes(
    user_id: int, *, skip: int = 0, limit: int | None = None
) -> list[MuteDoc]:
    """Return every mute record for a user, newest first.

    ``limit=None`` returns the full list (backwards compatible).
    """
    stmt = (
        select(*_MUTE_COLUMNS)
        .where(
            moderation_actions.c.target_user_id == user_id,
            moderation_actions.c.action_type == "mute",
        )
        .order_by(moderation_actions.c.created_at.desc())
        .offset(max(0, skip))
    )
    if limit is not None:
        stmt = stmt.limit(max(1, limit))
    rows = await db_call(lambda: fetch_all(stmt))
    return [_compose_mute(row) for row in rows]


async def user_mute_count(user_id: int) -> int:
    """Count every mute ever logged against the user."""
    total = await db_call(
        lambda: fetch_value(
            select(func.count())
            .select_from(moderation_actions)
            .where(
                moderation_actions.c.target_user_id == user_id,
                moderation_actions.c.action_type == "mute",
            )
        )
    )
    return int(total or 0)


def _compose_mute(row: dict[str, Any]) -> MuteDoc:
    """Return the mute document of one decision row."""
    origin = row.get("origin_chat_id")
    return MuteDoc(
        user_id=UserId(int(row["target_user_id"])),
        chat_id=ChatId(int(origin)) if origin is not None else None,
        reason=str(row["reason"]),
        admin_id=UserId(int(row["actor_user_id"])),
        timestamp=cast("datetime", row["created_at"]),
        duration_secs=cast("int | None", row.get("duration_seconds")),
    )


async def migrate_records(old_chat_id: int, new_chat_id: int) -> bool:
    """Repoint every mute record from ``old_chat_id`` to ``new_chat_id``.

    Called on basic-group to supergroup migration so /check mute history
    does not split across the legacy chat. Mute decisions are community
    scoped, so only the origin chat moves. Cancellation propagates.
    """
    return (
        await db_call(
            lambda: run(
                moderation_actions.update()
                .where(
                    moderation_actions.c.action_type == "mute",
                    moderation_actions.c.origin_chat_id == old_chat_id,
                )
                .values(origin_chat_id=new_chat_id)
            )
        )
        > 0
    )
