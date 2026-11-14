# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Group warning helpers over the moderation decision tables.

A warning is one decision in ``moderation_actions``. The count the
threshold reads is the ``warn_counts`` view, so the counter can never
drift from the history that produced it.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Any, cast

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from tcbot import cfg
from tcbot.database import moderation_db
from tcbot.database.base import moderation_actions
from tcbot.database.documents import WarnCountDoc, WarnDoc
from tcbot.database.engine import (
    db_call,
    fetch_all,
    fetch_one,
    fetch_value,
    run_transaction,
)
from tcbot.database.types import ChatId, UserId
from tcbot.utils.logger import get_logger
from tcbot.utils.time_and_date import utc_now

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime

    from sqlalchemy.engine import CursorResult
    from sqlalchemy.ext.asyncio import AsyncSession

log = get_logger(__name__)


def _lifetime_seconds(lifetime: timedelta) -> int:
    """Return the lifetime of a decision in whole seconds."""
    return max(int(lifetime.total_seconds()), 0)


# ──────────────────────────── Tables ────────────────────────────── #
# * The surrogate primary key stays out of the returned documents: the
# * helpers expose the community fields, not the storage identity.
_WARN_COLUMNS = (
    moderation_actions.c.id,
    moderation_actions.c.target_user_id,
    moderation_actions.c.actor_user_id,
    moderation_actions.c.reason,
    moderation_actions.c.chat_id,
    moderation_actions.c.created_at,
    moderation_actions.c.expires_at,
    moderation_actions.c.status,
    moderation_actions.c.case_id,
)


# ───────────────────────────── Counters ──────────────────────────── #
# * The counter is a view over the decisions, so it cannot fall behind
# * the history that produced it and needs no repair path.


async def warn_count(user_id: int, chat_id: int) -> int:
    """Get the current number of warnings for a user in a specific chat."""
    total = await db_call(
        lambda: fetch_value(
            text(
                "SELECT count FROM warn_counts "
                "WHERE chat_id = :chat_id AND user_id = :user_id"
            ).bindparams(chat_id=chat_id, user_id=user_id)
        )
    )
    return int(total or 0)


async def _open_case(
    sess: AsyncSession, target_id: int, admin_id: int, reason: str, chat_id: int
) -> int:
    """Return the open case of the target, or open one for the decision."""
    return await moderation_db.open_case(
        sess,
        target_id,
        admin_id,
        title=f"Warning of {target_id} in group {chat_id}",
        summary=reason,
        severity="low",
        requires_evidence=False,
    )


# ────────────────────────────── Records ──────────────────────────── #


async def add_warn(user_id: int, reason: str, admin_id: int, chat_id: int) -> int:
    """Add a new warning to a user in a specific chat.

    Returns the number of warnings the user now holds in that group. The
    decision and the case that holds it land in one transaction, and the
    count is read from the view, so it always agrees with the history.

    A warning carries its own deadline: the community schema treats the
    expiry as a fact of the decision, so it is set when the warning is
    filed. A warning that runs out stops counting towards the threshold
    without its history being rewritten.
    """
    now = utc_now()
    lifetime = timedelta(days=cfg.warn_expiry_days)
    expires_at = now + lifetime if cfg.warn_expiry_days > 0 else None

    async def _work(sess: AsyncSession) -> None:
        case_id = await _open_case(sess, user_id, admin_id, reason, chat_id)
        await sess.execute(
            pg_insert(moderation_actions).values(
                action_type="warn",
                scope_type="chat",
                chat_id=chat_id,
                origin_chat_id=chat_id,
                target_user_id=user_id,
                actor_user_id=admin_id,
                reason=reason,
                # * A warning that never expires has no duration: the
                # * deadline and the duration always describe the same
                # * decision.
                duration_seconds=(
                    _lifetime_seconds(lifetime) if expires_at is not None else None
                ),
                created_at=now,
                expires_at=expires_at,
                status="completed",
                case_id=case_id,
                action_origin="manual",
            )
        )
        # * The investigation ends with its decision: an open case is
        # * picked up by the next decision about the same user, so the
        # * history would collapse into one case per user.
        await moderation_db.close_case(sess, case_id, admin_id)

    await run_transaction(_work)
    return await warn_count(user_id, chat_id)


async def clear_warns(user_id: int, chat_id: int) -> int:
    """Revoke ALL warnings for a user in a specific chat.

    Raises the failure instead of returning 0: a 0 return means "nothing
    to clear", and reporting an outage as an empty state would mislead
    the moderator. The history stays readable, so the count the
    auto-ban threshold reads never outlives its decision.
    """
    return await _clear_warn_docs(
        user_id,
        [chat_id],
        scope=f"clear_warns user={user_id} chat={chat_id}",
    )


async def clear_all_warns(user_id: int) -> int:
    """Revoke ALL warnings for a user across every group.

    Used on federation threshold ban to ensure the user starts with a clean warn
    slate in every group after a potential unban, preventing immediate re-ban
    from stale per-group counts accumulated before the federation ban.

    Raises the failure like :func:`clear_warns` (a 0 return
    means "nothing cleared"); callers running inside ``gather`` inspect the
    captured exception instead.
    """
    return await _clear_warn_docs(
        user_id,
        None,
        scope=f"clear_all_warns user={user_id}",
    )


async def clear_warns_for_chats(user_id: int, chat_ids: Sequence[int]) -> int:
    """Revoke the warnings of *user_id* in the given groups only.

    Used by a partially applied federation threshold ban: the groups where
    the ban landed lose their stale warn counts, while the groups where the
    enforcement failed keep theirs so the threshold can fire again there.
    Clearing everything would leave the failed groups with no warning and no
    ban.

    Raises the failure like :func:`clear_warns`.
    """
    chats = [c for c in dict.fromkeys(chat_ids) if c]
    if not chats:
        return 0
    return await _clear_warn_docs(
        user_id,
        chats,
        scope=f"clear_warns_for_chats user={user_id} chats={len(chats)}",
    )


async def _clear_warn_docs(
    user_id: int,
    chat_ids: Sequence[int] | None,
    *,
    scope: str,
) -> int:
    """Revoke the warnings of a user; shared by every clear path.

    The decisions move to ``revoked`` instead of being deleted, so the
    history of the warning stays readable and the count drops on its own.

    Returns the number of revoked decisions. Raises the failure instead
    of returning 0: a 0 return means "nothing to clear", and reporting an
    outage as an empty state would mislead the moderator. Cancellation
    propagates instead of reporting success.
    """

    async def _work(sess: AsyncSession) -> int:
        stmt = moderation_actions.update().where(
            moderation_actions.c.target_user_id == user_id,
            moderation_actions.c.action_type == "warn",
            moderation_actions.c.status == "completed",
        )
        if chat_ids is not None:
            stmt = stmt.where(moderation_actions.c.chat_id.in_(chat_ids))
        result = await sess.execute(stmt.values(status="revoked", revoked_at=utc_now()))
        return cast("CursorResult", result).rowcount

    try:
        return int(await run_transaction(_work))
    except Exception:
        log.exception("%s failed", scope)
        raise


async def get_warns(
    user_id: int,
    chat_id: int,
    *,
    skip: int = 0,
    limit: int | None = None,
    newest_first: bool = False,
) -> list[WarnDoc]:
    """Return warn documents for a user in a chat, oldest first by default.

    Pass ``newest_first=True`` for paged newest-first views so page N
    holds the Nth-newest slice server-side; reversing an oldest-first
    page client-side would pin the newest records to the last pages.
    ``limit=None`` returns the full list (backwards compatible).
    """
    order = (
        (moderation_actions.c.created_at.desc(), moderation_actions.c.id.desc())
        if newest_first
        else (moderation_actions.c.created_at.asc(), moderation_actions.c.id.asc())
    )
    stmt = (
        select(*_WARN_COLUMNS)
        .where(
            moderation_actions.c.target_user_id == user_id,
            moderation_actions.c.action_type == "warn",
            moderation_actions.c.chat_id == chat_id,
            moderation_actions.c.status == "completed",
        )
        # * The surrogate id breaks timestamp ties so a page boundary
        # * cannot repeat or skip a record.
        .order_by(*order)
        .offset(max(0, skip))
    )
    if limit is not None:
        stmt = stmt.limit(max(1, limit))
    rows = await db_call(lambda: fetch_all(stmt))
    return [_compose_warn(row) for row in rows]


def _compose_warn(row: dict[str, Any]) -> WarnDoc:
    """Return the warning document of one decision row."""
    return WarnDoc(
        target_user_id=cast("UserId", int(row["target_user_id"])),
        reason=str(row["reason"]),
        actor_user_id=cast("UserId", int(row["actor_user_id"])),
        chat_id=cast("ChatId", int(row["chat_id"])),
        timestamp=cast("datetime", row["created_at"]),
    )


async def remove_last_warn(user_id: int, chat_id: int) -> bool:
    """Revoke the most recent warning of a user in a chat.

    Returns True when one was revoked. The decision moves to ``revoked``
    instead of being deleted, so the warning count drops without the
    history losing the record.
    """
    row = await db_call(
        lambda: fetch_one(
            select(moderation_actions.c.id)
            .where(
                moderation_actions.c.target_user_id == user_id,
                moderation_actions.c.action_type == "warn",
                moderation_actions.c.chat_id == chat_id,
                moderation_actions.c.status == "completed",
            )
            .order_by(
                moderation_actions.c.created_at.desc(), moderation_actions.c.id.desc()
            )
            .limit(1)
        )
    )
    if row is None:
        return False
    revoked = await _revoke_warn(int(row["id"]))
    return bool(revoked)


async def _revoke_warn(action_id: int) -> bool:
    """Move one warning decision to ``revoked``."""

    async def _work(sess: AsyncSession) -> bool:
        result = await sess.execute(
            moderation_actions.update()
            .where(
                moderation_actions.c.id == action_id,
                moderation_actions.c.status == "completed",
            )
            .values(status="revoked", revoked_at=utc_now())
        )
        return cast("CursorResult", result).rowcount > 0

    return await run_transaction(_work)


async def user_total_warns(user_id: int) -> int:
    """Return the historical number of warnings recorded against the user.

    Every warning the user ever received counts, including the ones that
    were cleared or that ran out. The count that is still in force is
    :func:`federation_warn_count`.
    """
    total = await db_call(
        lambda: fetch_value(
            select(func.count())
            .select_from(moderation_actions)
            .where(
                moderation_actions.c.target_user_id == user_id,
                moderation_actions.c.action_type == "warn",
            )
        )
    )
    return int(total or 0)


async def user_warn_groups(user_id: int) -> list[tuple[int, int]]:
    """Return [(chat_id, count), ...] for every group where the user has warns, newest first."""
    rows = await db_call(
        lambda: fetch_all(
            text(
                "SELECT chat_id, count FROM warn_counts "
                "WHERE user_id = :user_id AND count > 0"
            ).bindparams(user_id=user_id)
        )
    )
    return [(int(d["chat_id"]), int(d["count"])) for d in rows]


async def warn_count_doc(user_id: int, chat_id: int) -> WarnCountDoc | None:
    """Return the counter row of one user in one group."""
    row = await db_call(
        lambda: fetch_one(
            text(
                "SELECT chat_id, user_id, count FROM warn_counts "
                "WHERE chat_id = :chat_id AND user_id = :user_id"
            ).bindparams(chat_id=chat_id, user_id=user_id)
        )
    )
    return cast("WarnCountDoc | None", row)


# ───────────────────────────── Migration ─────────────────────────── #
# * The community schema moves a group as one transaction, so the
# * decisions of a group follow it through
# * :func:`tcbot.database.groups_db.migrate_group`. The warning counter
# * is a view over the decisions, so it follows them on its own.


async def federation_warn_count(user_id: int) -> int:
    """Total active warn count for a user across all federation chats.

    Sums the counter of every group through the view, avoiding a
    Python-side sum over a potentially large result set.  Returns 0 when
    the user has no active warnings.
    """
    total = await db_call(
        lambda: fetch_value(
            text(
                "SELECT COALESCE(SUM(count), 0) FROM warn_counts "
                "WHERE user_id = :user_id AND count > 0"
            ).bindparams(user_id=user_id)
        )
    )
    return int(total or 0)
