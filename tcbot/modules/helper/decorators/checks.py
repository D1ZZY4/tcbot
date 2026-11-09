# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Executor-vs-target permission checks shared by moderation entries."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from tcbot import cfg
from tcbot import database as db
from tcbot.modules.helper import identity, replies
from tcbot.modules.helper.locale import effective_locale
from tcbot.modules.helper.messages import safe_reply
from tcbot.utils.dispatch import throw_if_cancelled
from tcbot.utils.logger import get_logger

if TYPE_CHECKING:
    from telegram import Bot, Message

log = get_logger(__name__)


async def resolve_and_check(
    msg: Message,
    executor_id: int,
    target_id: int,
    *,
    min_role: str,
) -> tuple[str | None, str | None]:
    """Validate executor permission and target eligibility for moderation actions.

    Replies on the message itself when the executor lacks rank or the target
    outranks the executor, then returns ``(None, None)``.

    On success, returns ``(executor_role, target_role)``.
    """
    executor_role, target_role = await asyncio.gather(
        db.users_roles.get_effective_role(executor_id, fresh=True),
        db.users_roles.get_effective_role(target_id, fresh=True),
        return_exceptions=True,
    )
    throw_if_cancelled((executor_role, target_role))
    # * Moderation replies render in the group locale like every other
    # * command reply; resolution never raises (falls back to default).
    chat = msg.chat
    locale = await effective_locale(
        getattr(chat, "type", None), executor_id, getattr(chat, "id", 0)
    )
    executor_lookup_failed = isinstance(executor_role, BaseException)
    target_lookup_failed = isinstance(target_role, BaseException)
    if isinstance(executor_role, BaseException):
        log.warning(
            "resolve_and_check executor role lookup failed for %d: %s",
            executor_id,
            executor_role,
        )
        executor_role = None
    if isinstance(target_role, BaseException):
        log.warning(
            "resolve_and_check target role lookup failed for %d: %s",
            target_id,
            target_role,
        )
        target_role = None
    if executor_lookup_failed or target_lookup_failed:
        await safe_reply(
            msg,
            replies.refuse_role_lookup(locale, plain=True),
            log_label="resolve_and_check role-lookup",
            parse_mode=None,
        )
        return None, None
    if db.users_roles.role_rank(executor_role) < db.users_roles.role_rank(min_role):
        await safe_reply(
            msg,
            replies.refuse_rank_insufficient(locale, plain=True),
            log_label="resolve_and_check rank-insufficient",
            parse_mode=None,
        )
        return None, None

    if target_role and db.users_roles.role_rank(
        executor_role
    ) <= db.users_roles.role_rank(target_role):
        label = db.users_roles.ROLE_LABEL.get(target_role, target_role.capitalize())
        await safe_reply(
            msg,
            replies.refuse_outranked(label, locale, plain=True),
            log_label="resolve_and_check outrank",
            parse_mode=None,
        )
        return None, None

    return executor_role, target_role


async def classify_and_check(
    bot: Bot,
    admin_id: int,
    target_id: int,
    target_name: str | None,
    msg: Message,
    *,
    action: str,
    min_role: str,
    target_is_bot: bool | None = None,
) -> tuple[identity.Identity, str | None] | None:
    """Classify the target and validate executor rank in parallel, fail closed.

    Returns ``(ident, target_role)`` on success, or ``None`` after replying on
    the message when a lookup failed or the executor is not allowed to act.
    Cancellation always propagates.
    """
    ident, role_result = await asyncio.gather(
        identity.classify(
            bot, admin_id, target_id, target_name, target_is_bot=target_is_bot
        ),
        resolve_and_check(msg, admin_id, target_id, min_role=min_role),
        return_exceptions=True,
    )
    throw_if_cancelled((ident, role_result))
    if isinstance(ident, BaseException):
        log.exception("identity.classify failed in %s: %s", action, ident)
        return None
    if isinstance(role_result, BaseException):
        log.exception("resolve_and_check failed in %s: %s", action, role_result)
        return None
    # * isinstance + early return above already narrows role_result to the
    # * success tuple (asserts vanish under python -O). Guard first: when
    # * resolve_and_check already replied and rejected (e.g. target outranks
    # * executor), return so the caller does not send a second reply.
    executor_role, target_role = role_result
    if executor_role is None:
        return None
    return ident, target_role


async def recheck_executor_rank(
    msg: Message,
    executor_id: int,
    *,
    min_role: str,
) -> bool:
    """Re-verify the executor still meets ``min_role`` at enforcement time.

    Conversation Done/Skip/Continue taps can land long after the entry
    command passed its decorator: a moderator demoted mid-window must not
    enforce. Returns True when the tap may proceed, False after replying
    on ``msg`` when the rank lapsed or the lookup failed (fail closed).
    Cancellation always propagates.
    """
    chat = msg.chat
    locale = await effective_locale(
        getattr(chat, "type", None), executor_id, getattr(chat, "id", 0)
    )
    try:
        role = await db.users_roles.get_effective_role(executor_id, fresh=True)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        log.warning("recheck executor role lookup failed for %d: %s", executor_id, exc)
        await safe_reply(
            msg,
            replies.refuse_role_lookup(locale, plain=True),
            log_label="recheck role-lookup",
            parse_mode=None,
        )
        return False
    if db.users_roles.role_rank(role) < db.users_roles.role_rank(min_role):
        await safe_reply(
            msg,
            replies.refuse_rank_insufficient(locale, plain=True),
            log_label="recheck rank-insufficient",
            parse_mode=None,
        )
        return False
    return True


async def require_federation_origin(
    msg: Message,
    *,
    chat_id: int,
    chat_type: str,
    locale: str | None,
    allow_private: bool = True,
    log_label: str = "federation origin",
) -> bool:
    """Return True when the origin chat may host federation moderation.

    Private is allowed only when ``allow_private`` is set (federation-wide
    ban/unban/sync entries). Every group-like origin must be a connected
    group or a primary group: a disconnected group must not drive
    federation-wide enforcement or, for warns, record audit rows under a
    non-federation chat id that later aggregate into a federation auto-ban.
    Fail closed: a connection-state outage replies with the database retry
    notice and blocks the action. Cancellation always propagates.
    """
    if chat_type == "private":
        if allow_private:
            return True
        await safe_reply(
            msg,
            replies.err_group_only(locale, plain=True),
            log_label=log_label,
            parse_mode=None,
        )
        return False
    if cfg.is_primary_group(chat_id):
        return True
    try:
        connected = await db.groups_db.is_connected(chat_id, fresh=True)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        log.warning("is_connected check failed for chat=%d: %s", chat_id, exc)
        await safe_reply(
            msg,
            replies.err_db_retry(locale, plain=True),
            log_label=log_label,
            parse_mode=None,
        )
        return False
    if not connected:
        await safe_reply(
            msg,
            replies.err_group_not_found(locale, plain=True),
            log_label=log_label,
            parse_mode=None,
        )
        return False
    return True
