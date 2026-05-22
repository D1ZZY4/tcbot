# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""Group kick command entry point – validates permissions and delegates to kicking_flow."""

from __future__ import annotations

import asyncio
import logging

from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler

from tcbot import cfg
from tcbot.database.roles_db import ROLE_LABEL, get_effective_role, role_rank
from tcbot.modules.helper import decorators, extraction
from tcbot.modules.helper.formatter import mention
from tcbot.modules.helper.role_guard import auto_demote
from tcbot.modules.helper.workflows.kicking_flow import kick_conversation
from tcbot.modules.helper.workflows.reason_flow import (
    WAITING_PROOF,
    WAITING_REASON,
    parse_inline_reason,
    proof_kb,
    reason_kb,
    reason_noted_prompt,
    reason_prompt,
)
from tcbot.utils.prefixes import parse_cmd_args

log = logging.getLogger(__name__)


## ── Module & Help ─────────────────────────────────────────────────────────

__module_name__ = "Kick"
__help_text__ = (
    "<b>Commands & Aliases</b>\n"
    "<code>/tckick</code> (alias: <code>/tck</code>)\n\n"

    "<b>Who can use it</b>\n"
    "Tester and above (Founder / Admin / Developer / Tester).\n\n"

    "<b>Where to use it</b>\n"
    "Inside any connected group.\n\n"

    "<b>What it does</b>\n"
    "Removes a user from the <b>current group only</b> - this is not a federation-wide action. "
    "The user can rejoin via an invite link unless they are separately federation-banned.\n\n"
    "If the target holds a federation role (Tester / Developer / Admin), that role is "
    "automatically removed and they are notified by DM. A log entry is posted to the "
    "federation logs channel.\n\n"

    "<b>Flow</b>\n"
    "1. Run <code>/tckick</code> with the target (and optional inline reason).\n"
    "2. If no reason was given, the bot asks - reply with text or tap <b>Skip</b>.\n"
    "3. The bot asks for proof - send a photo/video or tap <b>Skip</b> to kick without proof.\n\n"

    "<b>How to specify the target</b>\n"
    "Reply to a message, or provide a user ID / @username after the command.\n\n"

    "<b>Examples</b>\n"
    "<code>/tckick @username being disruptive</code> - reason inline\n"
    "<code>/tck 123456789</code> - bot will ask for reason\n"
    "Or reply to a message and run <code>/tck</code>."
)


## ── Entry point ────────────────────────────────────────────────────────────

@decorators.ratelimiter(limit=5, period=60)
@decorators.log_execution
async def cmd_kick_entry(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
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
        await msg.reply_text("You need at least a Tester role to kick - not your call. 🚫")
        return ConversationHandler.END

    inline_reason = parse_inline_reason(args, has_explicit_target)

    if not target_id:
        await msg.reply_text(
            "Can't find that user - reply to their message or send me a user ID."
        )
        return ConversationHandler.END

    if target_id == ctx.bot.id:
        await msg.reply_text("Kick me? 😂 I run this place. Not happening.")
        return ConversationHandler.END

    target_role = await get_effective_role(target_id)
    if target_role:
        if role_rank(executor_role) <= role_rank(target_role):
            if target_role == "founder":
                await msg.reply_text(
                    f"That's {mention(target_id, target_name or 'the Founder')}, our Founder - "
                    "kicking the boss? Not happening. 👑",
                    parse_mode="HTML",
                )
            else:
                label = ROLE_LABEL.get(target_role, target_role.capitalize())
                await msg.reply_text(
                    f"That's a {cfg.community_name} {label} - they outrank you here, can't kick them."
                )
            return ConversationHandler.END
        await auto_demote(
            ctx.bot,
            target_id, target_name or str(target_id), target_role,
            admin.id, admin.first_name, "kick",
        )

    ctx.user_data.update({
        "kick_target_id":   target_id,
        "kick_target_name": target_name or str(target_id),
        "kick_proof_desc":  None,
    })

    target_mention = mention(target_id, target_name or str(target_id))

    if inline_reason:
        ctx.user_data["kick_reason"] = inline_reason
        await msg.reply_text(
            reason_noted_prompt("kick", inline_reason, target_mention),
            parse_mode="HTML",
            reply_markup=proof_kb("kick"),
        )
        return WAITING_PROOF

    await msg.reply_text(
        reason_prompt(target_mention, "kick"),
        parse_mode="HTML",
        reply_markup=reason_kb("kick"),
    )
    return WAITING_REASON


## ── Handlers ───────────────────────────────────────────────────────────────

__handlers__ = [kick_conversation(cmd_kick_entry)]
