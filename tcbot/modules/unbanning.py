# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""Federation unban command entry point: validates permissions and delegates to unban_flow."""

from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes, MessageHandler

from tcbot.modules.helper import decorators, extraction, identity, replies
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
        replies.PERM_DEV_ABOVE,
    ),
    (
        "Where to use",
        replies.CONTEXT_EXEC_OR_GROUP,
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
        replies.TARGET_SYNTAX,
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
    admin = update.effective_user
    args = parse_cmd_args(msg.text)
    target_id, target_fname = await extraction.extract_target(update, args, ctx.bot)
    if not target_id:
        await msg.reply_text(replies.ERR_NO_TARGET)
        return

    ident = await identity.classify(ctx.bot, admin.id, target_id, target_fname)
    refusal = identity.refuse_message("unban", ident)
    if refusal is not None:
        await msg.reply_text(refusal, parse_mode="HTML")
        return

    await execute_unban(update, ctx, target_id, target_fname)


# ──────────────────────────── Handlers ──────────────────────────── #

_UNBAN_CMDS = build_prefixed_filters("tcunban") | build_prefixed_filters("tcunb")

__handlers__ = [MessageHandler(_UNBAN_CMDS, cmd_unban)]
