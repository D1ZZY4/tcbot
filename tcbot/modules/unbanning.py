# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""Federation unban command entry point – validates permissions and delegates to unban_flow."""

from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes, MessageHandler

from tcbot import cfg
from tcbot import database as db
from tcbot.database.users_db import ROLE_LABEL, get_effective_role
from tcbot.modules.helper import decorators, extraction
from tcbot.modules.helper.formatter import mention
from tcbot.modules.helper.workflows.unban_flow import execute_unban
from tcbot.utils.prefixes import build_prefixed_filters, parse_cmd_args

log = logging.getLogger(__name__)


# ────────────────────── Module & Help Message ───────────────────── #

__module_name__ = "Unban"
__help_text__ = (
    "Lifts an active federation ban across <b>all connected groups</b> at once."
)

__help_sections__: list[tuple[str, str]] = [
    (
        "Commands & Aliases",
        "<code>/tcunban</code> (alias: <code>/tcunb</code>)",
    ),
    (
        "Who can use",
        "Developer and above (Founder / Admin / Developer).",
    ),
    (
        "Where to use",
        "Exec group, any connected group, or bot PM.",
    ),
    (
        "What it does",
        "Lifts an active federation ban on the target user. The unban is applied across "
        "<b>all connected groups</b> simultaneously so they can rejoin freely. A log entry "
        "is posted to the federation logs channel.\n\n"
        "If the user has no active federation ban, the bot will let you know and take no "
        "action.\n"
        "If the target's ban was under appeal, the appeal is also resolved as approved.",
    ),
    (
        "Target syntax",
        "Reply to a message, or provide a user ID / @username after the command.",
    ),
    (
        "Examples",
        "<code>/tcunban @username</code>\n"
        "<code>/tcunb 123456789</code>\n"
        "Or reply to a message and run <code>/tcunb</code>.",
    ),
]


# ──────────────────── Command Unban </tcunban> ──────────────────── #


@decorators.ratelimiter(limit=5, period=60)
@decorators.mod_only
@decorators.log_execution
async def cmd_unban(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
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
        fname = await db.users_db.get_first_name(target_id, str(target_id))
        await msg.reply_text(
            f"That's a {cfg.community_name} {role_label} - "
            "staff can't be federation-banned, so there's nothing to undo here.",
            parse_mode="HTML",
        )
        return

    await execute_unban(update, ctx, target_id, target_fname)


# ──────────────────────────── Handlers ──────────────────────────── #

_UNBAN_CMDS = build_prefixed_filters("tcunban") | build_prefixed_filters("tcunb")

__handlers__ = [MessageHandler(_UNBAN_CMDS, cmd_unban)]
