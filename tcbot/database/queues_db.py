# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Promotion request queue - manages promotion request queue for staff applications."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError

from tcbot.database.base import promotion_requests
from tcbot.database.documents import PromotionRequestDoc, RequestStatus
from tcbot.database.engine import (
    constraint_name,
    db_call,
    fetch_all,
    fetch_count,
    fetch_one,
    run,
)
from tcbot.database.types import UserId, make_short_id
from tcbot.utils.logger import get_logger
from tcbot.utils.time_and_date import utc_now

if TYPE_CHECKING:
    from datetime import datetime

log = get_logger(__name__)

# ──────────────────────────── Table ─────────────────────────────── #
# * The queue rows carry a surrogate id plus the request id as the natural
# * key, so a record holds every column and the row still has an identity.
_REQUEST_COLUMNS = [
    promotion_requests.c.request_id,
    promotion_requests.c.target_user_id,
    promotion_requests.c.requested_role_key,
    promotion_requests.c.requested_by_user_id,
    promotion_requests.c.status,
    promotion_requests.c.requested_at,
    promotion_requests.c.resolved_at,
    promotion_requests.c.resolved_by_user_id,
    promotion_requests.c.decision_note,
    promotion_requests.c.metadata,
]

# * The promotion list renders only these fields, so the query projects
# * them instead of shipping the whole row to the handler.
_LIST_COLUMNS = [
    promotion_requests.c.request_id,
    promotion_requests.c.target_user_id,
    promotion_requests.c.requested_role_key,
    promotion_requests.c.requested_at,
    promotion_requests.c.metadata,
]

# * Names of the two unique constraints that can reject an insert.
_CONSTRAINT_REQUEST_ID: str = "uq_promotion_requests_request_id"
_CONSTRAINT_PENDING: str = "uq_promotion_requests_pending_target"

# * Maximum number of rows the pending list returns. The list renders
# * one line per request, so an unbounded backlog would produce a
# * message the Telegram API refuses to send. The caller compares the
# * returned length with the real total and tells the operator that the
# * list is truncated.
_PENDING_PAGE_SIZE: int = 200

# * The role a request asks for when the caller does not name one.
_DEFAULT_REQUESTED_ROLE: str = "admin"

# ──────────────────────────── Errors ────────────────────────────── #
# * The driver reports every unique-constraint rejection as one error
# * type, so the two rejections the queue can hit are told apart by the
# * violated constraint name instead of by the error class.


class DuplicateKeyError(IntegrityError):
    """A unique-constraint rejection.

    Stands in for the driver error of the same name: it keeps the failed
    statement and the driver exception, so the violated constraint stays
    readable through ``constraint_name``.
    """


class AlreadyPendingError(DuplicateKeyError):
    """Target already has a pending promotion request.

    Subclasses DuplicateKeyError so callers checking for DuplicateKeyError
    keep working without changes.
    """


# ──────────────────────────── Mutations ─────────────────────────── #
# * Functions that create or modify promotion request records
# * Manages the queue's state for pending and resolved requests


def _is_pending_violation(exc: IntegrityError) -> bool:
    """Return True when exc came from the one-pending-per-user partial index.

    The partial unique index on target_user_id covers the pending rows only,
    while the random request id carries its own unique constraint, so the
    constraint name tells the two rejections apart.
    """
    return constraint_name(exc) == _CONSTRAINT_PENDING


def _is_request_id_violation(exc: IntegrityError) -> bool:
    """Return True when exc came from the unique request id constraint."""
    return constraint_name(exc) == _CONSTRAINT_REQUEST_ID


def _rebuild(exc: IntegrityError, kind: type[DuplicateKeyError]) -> DuplicateKeyError:
    """Rebuild a driver rejection as one of the queue's own error classes.

    The failed statement, the bound parameters, and the driver exception
    are carried over, so the violated constraint stays readable through
    ``constraint_name``.
    """
    return kind(exc.statement, exc.params, exc.orig or exc)


def _compose(row: dict[str, Any]) -> PromotionRequestDoc:
    """Return the request document of one queue row."""
    metadata = row.get("metadata") or {}
    if not isinstance(metadata, dict):
        metadata = {}
    return PromotionRequestDoc(
        request_id=cast("str", row["request_id"]),
        target_user_id=cast("UserId", int(row["target_user_id"])),
        username=cast("str | None", metadata.get("username")),
        first_name=cast("str", metadata.get("first_name") or ""),
        requested_role_key=cast("str", row["requested_role_key"]),
        requested_by_user_id=cast("UserId", int(row["requested_by_user_id"])),
        status=cast("RequestStatus", str(row["status"])),
        requested_at=cast("datetime", row["requested_at"]),
        resolved_at=cast("datetime | None", row.get("resolved_at")),
        resolved_by_user_id=cast("UserId | None", row.get("resolved_by_user_id")),
        decision_note=cast("str | None", row.get("decision_note")),
    )


async def enqueue(
    user_id: int,
    username: str | None,
    first_name: str,
    promoted_by: int,
    *,
    role_key: str = _DEFAULT_REQUESTED_ROLE,
) -> str:
    """Add a new promotion request to the queue.

    Retries once with a fresh ID only for genuine request_id collisions
    (mirrors ``bans_db.create_ban``). A partial-unique pending rejection
    raises AlreadyPendingError at once without burning the retry.
    """

    async def _insert(request_id: str) -> None:
        await db_call(
            lambda: run(
                pg_insert(promotion_requests).values(
                    request_id=request_id,
                    target_user_id=user_id,
                    requested_role_key=role_key,
                    requested_by_user_id=promoted_by,
                    status="pending",
                    requested_at=utc_now(),
                    resolved_at=None,
                    resolved_by_user_id=None,
                    metadata={"username": username, "first_name": first_name},
                )
            )
        )

    request_id = make_short_id()
    try:
        await _insert(request_id)
    except IntegrityError as exc:
        if _is_pending_violation(exc):
            raise _rebuild(exc, AlreadyPendingError) from exc
        if not _is_request_id_violation(exc):
            # * Only the random request id may collide. Any other
            # * integrity error is a real defect and must not be
            # * swallowed here.
            raise
        # * A 10-char random id collision is vanishingly rare but
        # * possible under concurrent requests: retry once with a fresh
        # * id instead of failing the promotion request.
        log.warning("Promotion request id %s collided; retrying", request_id)
        request_id = make_short_id()
        try:
            await _insert(request_id)
        except IntegrityError as retry_exc:
            if _is_pending_violation(retry_exc):
                raise _rebuild(retry_exc, AlreadyPendingError) from retry_exc
            if _is_request_id_violation(retry_exc):
                raise _rebuild(retry_exc, DuplicateKeyError) from retry_exc
            raise
    return request_id


# ───────────────────────────── Queries ──────────────────────────── #
# * Functions to retrieve promotion request data from the database
# * Includes lookups by ID, user, and counts of pending requests


async def get_request_by_id(request_id: str) -> PromotionRequestDoc | None:
    """Get a promotion request by its unique request ID."""
    row = await db_call(
        lambda: fetch_one(
            select(*_REQUEST_COLUMNS).where(
                promotion_requests.c.request_id == request_id
            )
        )
    )
    return _compose(row) if row else None


async def get_request(user_id: int) -> PromotionRequestDoc | None:
    """Get the pending request for a specific user."""
    row = await db_call(
        lambda: fetch_one(
            select(*_REQUEST_COLUMNS).where(
                promotion_requests.c.target_user_id == user_id,
                promotion_requests.c.status == "pending",
            )
        )
    )
    return _compose(row) if row else None


async def all_pending() -> list[PromotionRequestDoc]:
    """Get the currently pending promotion requests, oldest first.

    The list is capped at :data:`_PENDING_PAGE_SIZE` rows so the reply
    stays within the message size the Telegram API accepts. The caller
    compares the returned length with :func:`pending_count` and tells the
    operator that the list is truncated.
    """
    rows = await db_call(
        lambda: fetch_all(
            select(*_LIST_COLUMNS)
            .where(promotion_requests.c.status == "pending")
            .order_by(promotion_requests.c.requested_at.asc())
            .limit(_PENDING_PAGE_SIZE)
        )
    )
    return [_compose(row) for row in rows]


# * Total pending count for list headers. Kept byte-identical to
# * all_pending's status filter so "shown vs total" arithmetic in the
# * promote-list header stays meaningful.
async def pending_count() -> int:
    """Count all currently pending promotion requests."""
    return await db_call(
        lambda: fetch_count(
            select(func.count())
            .select_from(promotion_requests)
            .where(promotion_requests.c.status == "pending")
        )
    )


async def resolve(request_id: str, status: RequestStatus, resolved_by: int) -> bool:
    """Mark a pending promotion request as resolved.

    The ``pending`` filter makes the claim atomic: concurrent decisions on
    the same request resolve exactly once, and late taps get ``False``.
    """
    # ! Only terminal states may be stored: an arbitrary string here would
    # ! break the pending filters every other helper relies on.
    if status not in ("approved", "rejected"):
        raise ValueError(f"Refusing to resolve promotion request to {status!r}")
    affected = await db_call(
        lambda: run(
            promotion_requests.update()
            .where(
                promotion_requests.c.request_id == request_id,
                promotion_requests.c.status == "pending",
            )
            .values(
                status=status,
                resolved_at=utc_now(),
                resolved_by_user_id=resolved_by,
            )
        )
    )
    return affected > 0
