# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Promotion request submission and pending-queue listing."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from telegram.ext import ContextTypes

from tcbot import database as db
from tcbot.modules.admins.shared import (
    _RL_BULK_LIMIT,
    _RL_PERIOD_BULK_S,
    _RL_PERIOD_LONG_S,
    _RL_QUERY_LIMIT,
)
from tcbot.modules.helper import decorators
from tcbot.modules.helper.identity import ANONYMOUS_BOT_ID
from tcbot.modules.helper.workflows.promote_flow import Promote
from tcbot.utils.dispatch import throw_if_cancelled
from tcbot.utils.formatter import bold, code, user_ref
from tcbot.utils.i18n import Safe, t
from tcbot.utils.logger import get_logger

if TYPE_CHECKING:
    from telegram import Update

log = get_logger(__name__)


@decorators.ratelimiter(limit=_RL_BULK_LIMIT, period=_RL_PERIOD_BULK_S)
@decorators.log_execution
async def cmd_promote_request(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Submit a promotion request to the Founder.

    Checks the caller's existing role and any pending request in parallel.
    Rejects if the user already holds a federation role (no request needed) or
    already has an open request, then calls ``Promote.request_admin`` to create
    a new queue entry and notify the Founder.

    Note: identity.classify is intentionally not used here because the caller is
    the subject of the request (executor_id == target_id), which would always
    produce an ``Identity("self")`` refusal - incorrect for a self-submission flow.
    """
    user = update.effective_user
    msg = update.effective_message
    if user is None or msg is None:
        return
    # * Late-bound through the package namespace: callers patch
    # * tcbot.modules.admins.locale_for_update/safe_reply in tests, and a
    # * top-level import here would freeze the reference and cycle back
    # * through the package __init__.
    from tcbot.modules import admins as _admins  # noqa: PLC0415

    locale = await _admins.locale_for_update(update)

    # * Reject anonymous admins: a request from the group placeholder would
    # * reach the Founder with no attributable sender. Real humans send from
    # * their own account.
    if user.id == ANONYMOUS_BOT_ID:
        await _admins.safe_reply(
            msg,
            t("admins.request.anon_admin", locale, plain=True),
            log_label="cmd_promote_request anon-admin",
            parse_mode=None,
        )
        return
    if user.is_bot:
        await _admins.safe_reply(
            msg,
            t("admins.error.bot_target", locale, plain=True),
            log_label="cmd_promote_request bot-target",
            parse_mode=None,
        )
        return

    existing_role, existing = await asyncio.gather(
        db.users_roles.get_effective_role(user.id),
        db.queues_db.get_request(user.id),
        return_exceptions=True,
    )
    # * Fail closed like promote/demote: an outage must not green-light a
    # * request from an already-staff user or duplicate the queue.
    for _lookup in (existing_role, existing):
        if isinstance(_lookup, asyncio.CancelledError):
            raise _lookup
    if isinstance(existing_role, BaseException) or isinstance(existing, BaseException):
        log.warning(
            "cmd_promote_request lookup failed for user=%d: role=%s request=%s",
            user.id,
            existing_role,
            existing,
        )
        await _admins.safe_reply(
            msg,
            t("admins.error.role_lookup_failed", locale, plain=True),
            log_label="cmd_promote_request lookup-fail",
            parse_mode=None,
        )
        return
    if existing_role:
        label = db.users_roles.ROLE_LABEL.get(existing_role, existing_role or "unknown")
        label = label.capitalize()
        await _admins.safe_reply(
            msg,
            t("admins.request.already_role", locale, role=label, plain=True),
            log_label="cmd_promote_request already-role",
            parse_mode=None,
        )
        return

    if existing:
        await _admins.safe_reply(
            msg,
            t(
                "admins.request.existing",
                locale,
                id=Safe(code(existing.get("request_id", "unknown"))),
            ),
            log_label="cmd_promote_request existing-request",
        )
        return
    _, reply = await Promote.request_admin(
        ctx.bot,
        user.id,
        user.id,
        user.first_name or "unknown",
        user.username or "",
        locale,
    )
    await _admins.safe_reply(msg, reply, log_label="cmd_promote_request result")


@decorators.ratelimiter(limit=_RL_QUERY_LIMIT, period=_RL_PERIOD_LONG_S)
@decorators.staff_only
@decorators.log_execution
async def cmd_promote_list(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Reply with a formatted list of all pending promotion requests."""
    msg = update.effective_message
    if msg is None:
        return
    # * Same late binding as cmd_promote_request above.
    from tcbot.modules import admins as _admins  # noqa: PLC0415

    locale = await _admins.locale_for_update(update)
    pending_r, total_r = await asyncio.gather(
        db.queues_db.all_pending(),
        db.queues_db.pending_count(),
        return_exceptions=True,
    )
    throw_if_cancelled((pending_r, total_r))
    if isinstance(pending_r, BaseException) or isinstance(total_r, BaseException):
        log.warning(
            "all_pending/pending_count failed during promote_list: %s / %s",
            pending_r,
            total_r,
        )
        await _admins.safe_reply(
            msg,
            t("admins.error.role_lookup_failed", locale, plain=True),
            log_label="cmd_promote_list db-error",
            parse_mode=None,
        )
        return
    pending, total_pending = pending_r, total_r
    if not pending:
        await _admins.safe_reply(
            msg,
            t("admins.error.no_pending", locale, plain=True),
            log_label="cmd_promote_list no-pending",
            parse_mode=None,
        )
        return
    lines = [
        t(
            "admins.list.header",
            locale,
            title=Safe(
                bold(
                    t(
                        "admins.list.header_text",
                        locale,
                        n=total_pending
                        if total_pending > len(pending)
                        else len(pending),
                        plain=True,
                    )
                )
            ),
        )
        + "\n"
    ]
    # * all_pending returns at most 200 rows, so surface the true backlog
    # * count when the list is truncated.
    if total_pending > len(pending):
        lines.append(
            t(
                "admins.list.cap_notice",
                locale,
                shown=len(pending),
                total=total_pending,
            )
        )
    for req in pending:
        target_id = req.get("target_id", 0)
        target_fname = req.get("first_name", "unknown")
        uname_val = req.get("username")
        uname = (
            f"@{uname_val}"
            if uname_val
            else t("admins.list.no_username", locale, plain=True)
        )
        lines.append(
            t(
                "admins.list.row",
                locale,
                user=Safe(user_ref(target_id, target_fname, uname_val)),
                id=Safe(code(str(target_id))),
                uname=uname,
                req=Safe(code(req.get("request_id", "unknown"))),
            )
        )
    await _admins.safe_reply(msg, "\n".join(lines), log_label="cmd_promote_list result")
