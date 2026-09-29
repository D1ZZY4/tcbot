# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Unwarn, warnlist, and resetwarns management commands."""

from __future__ import annotations

from typing import TYPE_CHECKING

from telegram.ext import ContextTypes

from tcbot import cfg
from tcbot.modules.helper import decorators, extraction, identity, replies
from tcbot.modules.helper.decorators import resolve_and_check
from tcbot.modules.helper.locale import locale_for_update
from tcbot.modules.helper.parse_editmsg import safe_reply
from tcbot.modules.helper.workflows.warning_flow import (
    execute_resetwarns,
    execute_unwarn,
    execute_warnlist,
)
from tcbot.modules.warnings.warn import (
    _RL_CMD_PERIOD_S,
    _RL_PERIOD_S,
    _RL_READ_LIMIT,
    _RL_WARN_LIMIT,
)
from tcbot.utils.logger import get_logger
from tcbot.utils.prefixes import parse_cmd_args

if TYPE_CHECKING:
    from telegram import Update

log = get_logger(__name__)


# ─────────────────── Command Unwarn </tcunwarn> ─────────────────── #


@decorators.ratelimiter(limit=_RL_WARN_LIMIT, period=_RL_CMD_PERIOD_S)
@decorators.basic_mod_only
@decorators.log_execution
async def cmd_unwarn(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Remove one warning from the target in the current group.

    Resolves the target, runs the identity check, optionally emits a
    staff-action notice, then delegates to ``execute_unwarn``.
    """
    msg = update.effective_message
    if msg is None:
        return
    admin = update.effective_user
    if admin is None:
        return
    locale = await locale_for_update(update)
    args = parse_cmd_args(msg.text)
    target_id, target_name = await extraction.extract_target(update, args, ctx.bot)
    if not target_id:
        await safe_reply(
            msg,
            replies.err_cannot_resolve(locale, plain=True),
            log_label="cmd_unwarn no-target",
            parse_mode=None,
        )
        return

    classified = await decorators.classify_and_check(
        ctx.bot,
        admin.id,
        target_id,
        target_name,
        msg,
        action="unwarn",
        min_role="tester",
    )
    if classified is None:
        return
    ident, _ = classified

    refusal = identity.refuse_message("unwarn", ident, locale)
    if refusal is not None:
        await safe_reply(msg, refusal, log_label="cmd_unwarn refusal")
        return

    notice = identity.staff_notice("unwarn", ident, cfg.community_name, locale)
    if notice is not None:
        await safe_reply(msg, notice, log_label="cmd_unwarn notice")

    await execute_unwarn(update, ctx, target_id, target_name or str(target_id))


# ─────────────────── Command Warn List </warns> ─────────────────── #


@decorators.ratelimiter(limit=_RL_READ_LIMIT, period=_RL_PERIOD_S)
@decorators.basic_mod_only
@decorators.log_execution
async def cmd_warnlist(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Reply with a paginated warning history for the specified target user."""
    msg = update.effective_message
    if msg is None:
        return
    admin = update.effective_user
    if admin is None:
        return
    locale = await locale_for_update(update)
    args = parse_cmd_args(msg.text)
    target_id, target_name = await extraction.extract_target(update, args, ctx.bot)
    if not target_id:
        await safe_reply(
            msg,
            replies.err_cannot_resolve(locale, plain=True),
            log_label="cmd_warnlist no-target",
            parse_mode=None,
        )
        return

    role_result = await resolve_and_check(msg, admin.id, target_id, min_role="tester")
    # * resolve_and_check replies on rejection and returns (None, None).
    # * Read-only path: the rank check alone gates staff-history enumeration.
    if role_result[0] is None:
        return

    await execute_warnlist(update, ctx, target_id, target_name or str(target_id))


# ──────────────── Command Reset Warns </resetwarns> ─────────────── #


@decorators.ratelimiter(limit=_RL_WARN_LIMIT, period=_RL_CMD_PERIOD_S)
@decorators.basic_mod_only
@decorators.log_execution
async def cmd_resetwarns(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Clear all warnings for the target in the current group.

    Resolves the target, runs the identity check, optionally emits a
    staff-action notice, then delegates to ``execute_resetwarns``.
    """
    msg = update.effective_message
    if msg is None:
        return
    admin = update.effective_user
    if admin is None:
        return
    locale = await locale_for_update(update)
    args = parse_cmd_args(msg.text)
    target_id, target_name = await extraction.extract_target(update, args, ctx.bot)
    if not target_id:
        await safe_reply(
            msg,
            replies.err_cannot_resolve(locale, plain=True),
            log_label="cmd_resetwarns no-target",
            parse_mode=None,
        )
        return

    classified = await decorators.classify_and_check(
        ctx.bot,
        admin.id,
        target_id,
        target_name,
        msg,
        action="resetwarns",
        min_role="tester",
    )
    if classified is None:
        return
    ident, _ = classified

    refusal = identity.refuse_message("resetwarns", ident, locale)
    if refusal is not None:
        await safe_reply(msg, refusal, log_label="cmd_resetwarns refusal")
        return

    notice = identity.staff_notice("resetwarns", ident, cfg.community_name, locale)
    if notice is not None:
        await safe_reply(msg, notice, log_label="cmd_resetwarns notice")

    await execute_resetwarns(update, ctx, target_id, target_name or str(target_id))
