# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Studio

"""Warn, unwarn, warnlist, and resetwarns command handlers for per-group warning tracking."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from telegram.ext import ContextTypes, ConversationHandler, MessageHandler

from tcbot import cfg
from tcbot.modules.helper import decorators, extraction, identity, replies
from tcbot.modules.helper.decorators import resolve_and_check
from tcbot.modules.helper.formatter import mention
from tcbot.modules.helper.workflows.reason_flow import (
    WAITING_PROOF,
    WAITING_REASON,
    parse_inline_reason,
)
from tcbot.modules.helper.workflows.warning_flow import (
    WARN_LIMIT,
    execute_resetwarns,
    execute_unwarn,
    execute_warnlist,
    proof,
    reason,
    warn_conversation,
)
from tcbot.utils.prefixes import build_prefixed_filters, parse_cmd_args

if TYPE_CHECKING:
    from telegram import Update

log = logging.getLogger(__name__)

# ─────────────────────── Rate-limiter constants ──────────────────── #
_RL_PERIOD_S: int = 30
_RL_CMD_PERIOD_S: int = 60
_RL_WARN_LIMIT: int = 5
_RL_READ_LIMIT: int = 8


# ────────────────────── Module & Help Message ───────────────────── #

__module_name__ = "Warnings"
__help_text__ = (
    "Per-group warning tracking. At "
    f"<b>{WARN_LIMIT} warnings</b> the user is automatically banned from the group "
    "and their record cleared."
)

__help_sections__: list[tuple[str, str]] = [
    (
        replies.SEC_COMMANDS,
        "<code>/tcwarn</code> (alias: <code>/tcw</code>)\n"
        "<code>/tcunwarn</code> (alias: <code>/tcunw</code>)\n"
        "<code>/warns</code> (alias: <code>/warnlist</code>)\n"
        "<code>/resetwarns</code> (alias: <code>/clearwarns</code>)",
    ),
    (
        replies.SEC_WHO,
        "<b>/tcwarn</b>, <b>/tcunwarn</b>, <b>/resetwarns</b>: Tester and above.\n"
        "<b>/warns</b>: anyone.",
    ),
    (
        replies.SEC_WHERE,
        replies.WHERE_CONNECTED_GROUP,
    ),
    (
        replies.SEC_WHAT,
        f"<b>/tcwarn</b>: issues a formal warning. Warnings are tracked <b>per-group</b> and "
        f"do not carry across connected groups. At <b>{WARN_LIMIT} warnings</b>, the user is "
        f"automatically banned from the group and their warning record is cleared.\n\n"
        f"<b>/tcunwarn</b>: removes the user's most recent warning in the current group.\n\n"
        f"<b>/warns</b>: shows the current warning count and full list of reasons.\n\n"
        f"<b>/resetwarns</b>: clears all warnings for a user in the current group at once, "
        f"without triggering the ban threshold.",
    ),
    (
        "Flow (/tcwarn)",
        "1. Run <code>/tcwarn</code> with the target (and optional inline reason).\n"
        "2. If no reason was given, the bot asks - reply with text.\n"
        "3. The bot asks for proof - send a photo/video or tap <b>Skip</b>.",
    ),
    (
        replies.SEC_TARGET,
        replies.TARGET_SYNTAX,
    ),
    (
        replies.SEC_EXAMPLES,
        "<code>/tcwarn @username spamming</code>: reason inline\n"
        "<code>/tcw 123456789</code>: bot will ask for reason\n"
        "<code>/tcunwarn @username</code>\n"
        "<code>/warns @username</code>\n"
        "<code>/resetwarns @username</code>",
    ),
]


# ──────────────────────── Helper Functions ──────────────────────── #
# (Per-target identity classification now lives in helper/identity.py.)


# ───────────────────── Command Warn </tcwarn> ───────────────────── #


@decorators.ratelimiter(limit=_RL_WARN_LIMIT, period=_RL_CMD_PERIOD_S)
@decorators.basic_mod_only
@decorators.log_execution
async def cmd_warn_entry(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    """Entry point for the warn flow.

    Resolves the target, runs identity and role checks in parallel, then either
    skips to the proof step (when an inline reason is provided) or opens the
    reason-collection step. Returns ``ConversationHandler.END`` on any validation
    failure.
    """
    msg = update.effective_message
    admin = update.effective_user

    args = parse_cmd_args(msg.text)
    has_explicit_target = bool(args) and (
        args[0].lstrip("-").isdigit() or args[0].startswith("@")
    )
    target_id, target_name = await extraction.extract_target(update, args, ctx.bot)

    inline_reason = parse_inline_reason(args, has_explicit_target=has_explicit_target)

    if not target_id:
        try:
            await msg.reply_text(replies.ERR_CANNOT_RESOLVE)
        except Exception as exc:
            log.debug("cmd_warn_entry no-target reply failed: %s", exc)
        return ConversationHandler.END

    ident, role_result = await asyncio.gather(
        identity.classify(ctx.bot, admin.id, target_id, target_name),
        resolve_and_check(msg, admin.id, target_id, min_role="tester"),
        return_exceptions=True,
    )
    if isinstance(ident, BaseException):
        log.exception("identity.classify failed in cmd_warn: %s", ident)
        return ConversationHandler.END
    if isinstance(role_result, BaseException):
        log.exception("resolve_and_check failed in cmd_warn: %s", role_result)
        return ConversationHandler.END
    executor_role, _ = role_result
    # * Guard first: if resolve_and_check already replied and rejected (e.g. target
    # * outranks executor), skip the identity refusal to avoid sending two replies.
    if executor_role is None:
        return ConversationHandler.END

    refusal = identity.refuse_message("warn", ident)
    if refusal is not None:
        try:
            await msg.reply_text(refusal, parse_mode="HTML")
        except Exception as exc:
            log.debug("cmd_warn_entry refusal reply failed: %s", exc)
        return ConversationHandler.END

    notice = identity.staff_notice("warn", ident, cfg.community_name)
    if notice is not None:
        try:
            await msg.reply_text(notice, parse_mode="HTML")
        except Exception as exc:
            log.debug("cmd_warn_entry staff notice reply failed: %s", exc)

    ctx.user_data.update(
        {
            "warn_target_id": target_id,
            "warn_target_name": target_name or str(target_id),
            "warn_proof_desc": None,
        }
    )

    target_mention = mention(target_id, target_name or str(target_id))

    _WARN_KEYS = ("warn_target_id", "warn_target_name", "warn_proof_desc")

    if inline_reason:
        ctx.user_data["warn_reason"] = inline_reason
        try:
            await msg.reply_text(
                proof.noted_prompt("warn", inline_reason, target_mention),
                parse_mode="HTML",
                reply_markup=proof.keyboard(),
            )
        except Exception as exc:
            log.debug("cmd_warn_entry proof-prompt reply failed: %s", exc)
            for key in (*_WARN_KEYS, "warn_reason"):
                ctx.user_data.pop(key, None)
            return ConversationHandler.END
        return WAITING_PROOF

    try:
        await msg.reply_text(
            reason.prompt(target_mention, "warn"),
            parse_mode="HTML",
            reply_markup=reason.keyboard(),
        )
    except Exception as exc:
        log.debug("cmd_warn_entry reason-prompt reply failed: %s", exc)
        for key in _WARN_KEYS:
            ctx.user_data.pop(key, None)
        return ConversationHandler.END
    return WAITING_REASON


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
    admin = update.effective_user
    args = parse_cmd_args(msg.text)
    target_id, target_name = await extraction.extract_target(update, args, ctx.bot)
    if not target_id:
        try:
            await msg.reply_text(replies.ERR_CANNOT_RESOLVE)
        except Exception as exc:
            log.debug("cmd_unwarn no-target reply failed: %s", exc)
        return

    ident, role_result = await asyncio.gather(
        identity.classify(ctx.bot, admin.id, target_id, target_name),
        resolve_and_check(msg, admin.id, target_id, min_role="tester"),
        return_exceptions=True,
    )
    if isinstance(ident, BaseException):
        log.exception("identity.classify failed in cmd_unwarn: %s", ident)
        return
    if isinstance(role_result, BaseException):
        log.exception("resolve_and_check failed in cmd_unwarn: %s", role_result)
        return
    executor_role, _ = role_result
    # * Guard first: if resolve_and_check already replied and rejected (e.g. target
    # * outranks executor), skip the identity refusal to avoid sending two replies.
    if executor_role is None:
        return

    refusal = identity.refuse_message("unwarn", ident)
    if refusal is not None:
        try:
            await msg.reply_text(refusal, parse_mode="HTML")
        except Exception as exc:
            log.debug("cmd_unwarn refusal reply failed: %s", exc)
        return

    notice = identity.staff_notice("unwarn", ident, cfg.community_name)
    if notice is not None:
        try:
            await msg.reply_text(notice, parse_mode="HTML")
        except Exception as exc:
            log.debug("cmd_unwarn notice reply failed: %s", exc)

    await execute_unwarn(update, ctx, target_id, target_name or str(target_id))


# ─────────────────── Command Warn List </warns> ─────────────────── #


@decorators.ratelimiter(limit=_RL_READ_LIMIT, period=_RL_PERIOD_S)
@decorators.log_execution
async def cmd_warnlist(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Reply with a paginated warning history for the specified target user."""
    msg = update.effective_message
    args = parse_cmd_args(msg.text)
    target_id, target_name = await extraction.extract_target(update, args, ctx.bot)
    if not target_id:
        try:
            await msg.reply_text(replies.ERR_NO_TARGET)
        except Exception as exc:
            log.debug("cmd_warnlist no-target reply failed: %s", exc)
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
    admin = update.effective_user
    args = parse_cmd_args(msg.text)
    target_id, target_name = await extraction.extract_target(update, args, ctx.bot)
    if not target_id:
        try:
            await msg.reply_text(replies.ERR_NO_TARGET)
        except Exception as exc:
            log.debug("cmd_resetwarns no-target reply failed: %s", exc)
        return

    ident, role_result = await asyncio.gather(
        identity.classify(ctx.bot, admin.id, target_id, target_name),
        resolve_and_check(msg, admin.id, target_id, min_role="tester"),
        return_exceptions=True,
    )
    if isinstance(ident, BaseException):
        log.exception("identity.classify failed in cmd_resetwarns: %s", ident)
        return
    if isinstance(role_result, BaseException):
        log.exception("resolve_and_check failed in cmd_resetwarns: %s", role_result)
        return
    executor_role, _ = role_result
    # * Guard first: if resolve_and_check already replied and rejected (e.g. target
    # * outranks executor), skip the identity refusal to avoid sending two replies.
    if executor_role is None:
        return

    refusal = identity.refuse_message("resetwarns", ident)
    if refusal is not None:
        try:
            await msg.reply_text(refusal, parse_mode="HTML")
        except Exception as exc:
            log.debug("cmd_resetwarns refusal reply failed: %s", exc)
        return

    notice = identity.staff_notice("resetwarns", ident, cfg.community_name)
    if notice is not None:
        try:
            await msg.reply_text(notice, parse_mode="HTML")
        except Exception as exc:
            log.debug("cmd_resetwarns notice reply failed: %s", exc)

    await execute_resetwarns(update, ctx, target_id, target_name or str(target_id))


# ──────────────────────────── Handlers ──────────────────────────── #

_WARN_CMDS = build_prefixed_filters("tcwarn") | build_prefixed_filters("tcw")
_UNWARN_CMDS = build_prefixed_filters("tcunwarn") | build_prefixed_filters("tcunw")
_WARNLIST_CMDS = build_prefixed_filters("warns") | build_prefixed_filters("warnlist")
_RESET_CMDS = build_prefixed_filters("resetwarns") | build_prefixed_filters(
    "clearwarns"
)

# * Commands that must NOT be swallowed by the warn conversation fallback.
_WARN_ESCAPE_CMDS = _UNWARN_CMDS | _WARNLIST_CMDS | _RESET_CMDS

__handlers__ = [
    warn_conversation(cmd_warn_entry, _WARN_CMDS, escape_filter=_WARN_ESCAPE_CMDS),
    MessageHandler(_UNWARN_CMDS, cmd_unwarn),
    MessageHandler(_WARNLIST_CMDS, cmd_warnlist),
    MessageHandler(_RESET_CMDS, cmd_resetwarns),
]
