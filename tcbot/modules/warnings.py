# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""Warn, unwarn, warnlist, and resetwarns command handlers for per-group warning tracking."""

from __future__ import annotations

import asyncio
import logging

from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler, MessageHandler

from tcbot import cfg, database as db
from tcbot.database.roles_db import ROLE_LABEL, get_effective_role, role_rank
from tcbot.modules.helper import decorators, extraction
from tcbot.modules.helper.formatter import mention
from tcbot.modules.helper.workflows.reason_flow import (
    parse_inline_reason,
    proof_kb,
    reason_noted_prompt,
    reason_only_kb,
    reason_prompt,
)
from tcbot.modules.helper.workflows.reason_flow import (
    WAITING_PROOF,
    WAITING_REASON,
)
from tcbot.modules.helper.workflows.warning_flow import (
    WARN_LIMIT,
    execute_resetwarns,
    execute_unwarn,
    execute_warnlist,
    warn_conversation,
)
from tcbot.utils.prefixes import build_prefixed_filters, parse_cmd_args

log = logging.getLogger(__name__)


## ── Module & Help ─────────────────────────────────────────────────────────

__module_name__ = "Warnings"
__help_text__ = (
    "<b>Commands & Aliases</b>\n"
    f"<code>/tcwarn</code> (alias: <code>/tcw</code>)\n"
    f"<code>/tcunwarn</code> (alias: <code>/tcunw</code>)\n"
    "<code>/warns</code> (alias: <code>/warnlist</code>)\n"
    "<code>/resetwarns</code> (alias: <code>/clearwarns</code>)\n\n"

    "<b>Who can use it</b>\n"
    f"<code>/tcwarn</code>, <code>/tcunwarn</code>, <code>/resetwarns</code>: Tester and above.\n"
    "<code>/warns</code>: anyone.\n\n"

    "<b>Where to use it</b>\n"
    "Inside any connected group.\n\n"

    "<b>What it does</b>\n"
    f"<code>/tcwarn</code>: issues a formal warning to a user in the current group. "
    "Warnings are tracked <b>per-group</b> and do not carry across connected groups. "
    f"At <b>{WARN_LIMIT} warnings</b>, the user is automatically banned from the group "
    "and their warning record is cleared.\n\n"
    "<code>/tcunwarn</code>: removes the user's most recent warning in the current group.\n\n"
    "<code>/warns</code>: shows the current warning count and full list of reasons "
    "for a user in the current group.\n\n"
    "<code>/resetwarns</code>: clears all warnings for a user in the current group at once, "
    "without triggering the ban threshold.\n\n"

    "<b>Flow (/tcwarn)</b>\n"
    "1. Run <code>/tcwarn</code> with the target (and optional inline reason).\n"
    "2. If no reason was given, the bot asks - reply with text.\n"
    "3. The bot asks for proof - send a photo/video or tap <b>Skip</b> to warn without proof.\n\n"

    "<b>How to specify the target</b>\n"
    "Reply to a message, or provide a user ID / @username after the command.\n\n"

    "<b>Examples</b>\n"
    "<code>/tcwarn @username spamming</code> - reason inline\n"
    "<code>/tcw 123456789</code> - bot will ask for reason\n"
    "<code>/tcunwarn @username</code>\n"
    "<code>/warns @username</code>\n"
    "<code>/resetwarns @username</code>"
)


## ── Helpers ────────────────────────────────────────────────────────────────

async def _role_note(
    target_id: int,
    target_name: str | None,
    target_role: str,
) -> tuple[str, str]:
    """Return (fname, role_label) for a staff target."""
    fname      = await db.users_db.get_first_name(target_id, target_name or str(target_id))
    role_label = ROLE_LABEL.get(target_role, target_role)
    return fname, role_label


## ── /tcwarn entry point ────────────────────────────────────────────────────

@decorators.ratelimiter(limit=5, period=60)
@decorators.log_execution
async def cmd_warn_entry(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    msg   = update.effective_message
    admin = update.effective_user

    args = parse_cmd_args(msg.text)
    has_explicit_target = bool(args) and (
        args[0].lstrip("-").isdigit() or args[0].startswith("@")
    )
    ## Role check and target resolution run in parallel
    executor_role, (target_id, target_name) = await asyncio.gather(
        get_effective_role(admin.id),
        extraction.extract_target(update, args, ctx.bot),
    )
    if role_rank(executor_role) < role_rank("tester"):
        await msg.reply_text("You need at least a Tester role to warn users - not your call. 🚫")
        return ConversationHandler.END

    inline_reason = parse_inline_reason(args, has_explicit_target)

    if not target_id:
        await msg.reply_text(
            "Can't find that user - reply to their message or send me a user ID."
        )
        return ConversationHandler.END

    if target_id == ctx.bot.id:
        await msg.reply_text("Warn me? 😄 I'm the one who manages warnings around here.")
        return ConversationHandler.END

    target_role = await get_effective_role(target_id)
    if target_role:
        if role_rank(executor_role) <= role_rank(target_role):
            if target_role == "founder":
                await msg.reply_text(
                    f"That's {mention(target_id, target_name or 'the Founder')}, our Founder - "
                    "warning them? That's a hard no. 👑",
                    parse_mode="HTML",
                )
            else:
                label = ROLE_LABEL.get(target_role, target_role.capitalize())
                await msg.reply_text(
                    f"That's a {cfg.community_name} {label} - they outrank you here, can't warn them."
                )
            return ConversationHandler.END

    ctx.user_data.update({
        "warn_target_id":   target_id,
        "warn_target_name": target_name or str(target_id),
        "warn_proof_desc":  None,
    })

    target_mention = mention(target_id, target_name or str(target_id))

    if inline_reason:
        ctx.user_data["warn_reason"] = inline_reason
        await msg.reply_text(
            reason_noted_prompt("warn", inline_reason, target_mention),
            parse_mode="HTML",
            reply_markup=proof_kb("warn"),
        )
        return WAITING_PROOF

    await msg.reply_text(
        reason_prompt(target_mention, "warn"),
        parse_mode="HTML",
        reply_markup=reason_only_kb("warn"),
    )
    return WAITING_REASON


## ── /tcunwarn ───────────────────────────────────────────────────────────────

@decorators.ratelimiter(limit=5, period=60)
@decorators.basic_mod_only
@decorators.log_execution
async def cmd_unwarn(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    msg  = update.effective_message
    args = parse_cmd_args(msg.text)
    target_id, target_name = await extraction.extract_target(update, args, ctx.bot)
    if not target_id:
        await msg.reply_text("Specify a target - reply to a message or provide a user ID.")
        return

    if target_id == ctx.bot.id:
        await msg.reply_text(
            f"That's {mention(ctx.bot.id, ctx.bot.first_name or 'me')} - "
            "zero warnings here, ever. Nothing to remove. 😄",
            parse_mode="HTML",
        )
        return

    target_role = await get_effective_role(target_id)
    if target_role == "founder":
        fname = await db.users_db.get_first_name(target_id, "the Founder")
        await msg.reply_text(
            f"That's {mention(target_id, fname)}, the Founder - no warnings on record. 👑",
            parse_mode="HTML",
        )
        return
    if target_role in ("admin", "developer", "tester"):
        fname, role_label = await _role_note(target_id, target_name, target_role)
        await msg.reply_text(
            f"Heads up - {mention(target_id, fname)} is a {cfg.community_name} {role_label}. "
            "Proceeding with unwarn anyway.",
            parse_mode="HTML",
        )

    await execute_unwarn(update, ctx, target_id, target_name or str(target_id))


## ── /warns ──────────────────────────────────────────────────────────────────

@decorators.ratelimiter(limit=8, period=30)
@decorators.log_execution
async def cmd_warnlist(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    args = parse_cmd_args(update.effective_message.text)
    target_id, target_name = await extraction.extract_target(update, args, ctx.bot)
    if not target_id:
        await update.effective_message.reply_text(
            "Specify a target - reply to a message or provide a user ID."
        )
        return
    await execute_warnlist(update, ctx, target_id, target_name or str(target_id))


## ── /resetwarns ─────────────────────────────────────────────────────────────

@decorators.ratelimiter(limit=5, period=60)
@decorators.basic_mod_only
@decorators.log_execution
async def cmd_resetwarns(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    msg  = update.effective_message
    args = parse_cmd_args(msg.text)
    target_id, target_name = await extraction.extract_target(update, args, ctx.bot)
    if not target_id:
        await msg.reply_text("Specify a target - reply to a message or provide a user ID.")
        return

    if target_id == ctx.bot.id:
        await msg.reply_text(
            f"That's {mention(ctx.bot.id, ctx.bot.first_name or 'me')} - "
            "already at zero, always. Nothing to clear. 😄",
            parse_mode="HTML",
        )
        return

    target_role = await get_effective_role(target_id)
    if target_role == "founder":
        fname = await db.users_db.get_first_name(target_id, "the Founder")
        await msg.reply_text(
            f"That's {mention(target_id, fname)}, the Founder - no warnings to clear. 👑",
            parse_mode="HTML",
        )
        return
    if target_role in ("admin", "developer", "tester"):
        fname, role_label = await _role_note(target_id, target_name, target_role)
        await msg.reply_text(
            f"Heads up - {mention(target_id, fname)} is a {cfg.community_name} {role_label}. "
            "Proceeding with reset anyway.",
            parse_mode="HTML",
        )

    await execute_resetwarns(update, ctx, target_id, target_name or str(target_id))


## ── Handlers ───────────────────────────────────────────────────────────────

_UNWARN_FILTER   = build_prefixed_filters("tcunwarn") | build_prefixed_filters("tcunw")
_WARNLIST_FILTER = build_prefixed_filters("warns")    | build_prefixed_filters("warnlist")
_RESET_FILTER    = build_prefixed_filters("resetwarns") | build_prefixed_filters("clearwarns")

__handlers__ = [
    warn_conversation(cmd_warn_entry),
    MessageHandler(_UNWARN_FILTER,   cmd_unwarn),
    MessageHandler(_WARNLIST_FILTER, cmd_warnlist),
    MessageHandler(_RESET_FILTER,    cmd_resetwarns),
]
