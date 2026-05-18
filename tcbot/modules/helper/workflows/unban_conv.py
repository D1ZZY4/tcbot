# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""
Unban command handler and MessageHandler factory
"""

from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes, MessageHandler

from tcbot import cfg, database as db
from tcbot.database.roles_db import ROLE_LABEL, get_effective_role
from tcbot.modules.helper import decorators, extraction
from tcbot.modules.helper.formatter import mention
from tcbot.modules.helper.workflows.unban_flow import execute_unban
from tcbot.utils.prefixes import build_prefixed_filters, parse_cmd_args


## ── /tcunban command ────────────────────────────────────────────────────────

@decorators.ratelimiter(limit=5, period=60)
@decorators.mod_only
@decorators.log_execution
async def cmd_unban(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    msg  = update.effective_message
    args = parse_cmd_args(msg.text)
    target_id, target_fname = await extraction.extract_target(update, args, ctx.bot)
    if not target_id:
        await msg.reply_text(
            "Specify a target - reply to a message or provide a user ID."
        )
        return

    if target_id == ctx.bot.id:
        await msg.reply_text(
            f"That's {mention(ctx.bot.id, ctx.bot.first_name or 'me')} - I manage the bans, "
            "not receive them. Nothing to undo here. 😄",
            parse_mode="HTML",
        )
        return

    target_role = await get_effective_role(target_id)
    if target_role == "founder":
        fname = await db.users_db.get_first_name(target_id, "the Founder")
        await msg.reply_text(
            f"That's {mention(target_id, fname)}, the Founder - "
            "they've never been banned. Nothing to undo. 👑",
            parse_mode="HTML",
        )
        return
    if target_role in ("admin", "developer", "tester"):
        role_label = ROLE_LABEL.get(target_role, target_role)
        fname      = await db.users_db.get_first_name(target_id, str(target_id))
        await msg.reply_text(
            f"That's a {cfg.community_name} {role_label} - "
            "staff can't be federation-banned, so there's nothing to undo here.",
            parse_mode="HTML",
        )
        return

    await execute_unban(update, ctx, target_id, target_fname)


## ── Handler factory ────────────────────────────────────────────────────────

_FILTER = (
    build_prefixed_filters("tcunban")
    | build_prefixed_filters("tcunb")
)


def build_handler() -> MessageHandler:
    """Return the /tcunban MessageHandler."""
    return MessageHandler(_FILTER, cmd_unban)
