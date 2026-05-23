# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""Federation ban command entry point – validates permissions and starts the ban flow."""

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
from tcbot.modules.helper.workflows.ban_flow import (
    WAITING_PROOF,
    ban_conversation,
    proof,
)
from tcbot.utils.prefixes import build_prefixed_filters, parse_cmd_args

log = logging.getLogger(__name__)


# ────────────────────── Module & Help Message ───────────────────── #

__module_name__ = "Ban"
__help_text__ = (
    "<b>Commands & Aliases</b>\n"
    "<code>/tcban</code> (alias: <code>/tcb</code>)\n\n"
    "<b>Who can use it</b>\n"
    "Developer and above (Founder / Admin / Developer).\n\n"
    "<b>Where to use it</b>\n"
    "Exec group, any connected group, or bot PM.\n\n"
    "<b>What it does</b>\n"
    "Issues a <b>federation-wide ban</b> on the target, applied across all connected groups "
    "automatically. A reason is required - provide it directly after the target in the command.\n\n"
    "After the command, the bot walks you through the proof step: send one or more photos or "
    "videos as evidence, then tap <b>Done</b>. Tap <b>Skip</b> if you have no proof. "
    "The ban record and proof are logged to the federation log channel.\n\n"
    "If the user already has an active ban, the existing record is updated with the new reason "
    "and proof rather than creating a duplicate.\n"
    "If the target holds a federation role (Tester / Developer / Admin), that role is "
    "automatically removed and they are notified by DM before the ban is enforced.\n\n"
    "<b>How to specify the target</b>\n"
    "Reply to a message, or provide a user ID / @username after the command.\n\n"
    "<b>Examples</b>\n"
    "<code>/tcban @username spamming in connected groups</code>\n"
    "<code>/tcban 123456789 scamming members</code>\n"
    "Or reply to a message and run <code>/tcb reason here</code>."
)


# ────────────────────── Command Ban </tcban> ────────────────────── #


@decorators.ratelimiter(limit=3, period=60)
@decorators.log_execution
async def cmd_ban_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    msg = update.effective_message
    admin = update.effective_user
    raw_args = parse_cmd_args(msg.text)

    has_explicit_target = bool(raw_args) and (
        raw_args[0].lstrip("-").isdigit() or raw_args[0].startswith("@")
    )
    # * Role check and target resolution run in parallel
    executor_role, (target_id, target_fname) = await asyncio.gather(
        get_effective_role(admin.id),
        extraction.extract_target(update, raw_args, ctx.bot),
    )
    if role_rank(executor_role) < role_rank("developer"):
        await msg.reply_text(
            "You need Developer rank or above to issue bans. Not your call. 🚫"
        )
        return ConversationHandler.END

    ban_reason = " ".join(raw_args[1:] if has_explicit_target else raw_args).strip()

    if not target_id:
        await msg.reply_text(
            "Cannot resolve target. Reply to a message or provide a user ID."
        )
        return ConversationHandler.END

    if not ban_reason:
        await msg.reply_text("A reason is required - /tcban <target> <reason>.")
        return ConversationHandler.END

    if target_id == ctx.bot.id:
        await msg.reply_text(
            "That's me you're trying to ban 😐 - I keep this federation running. Nice try."
        )
        return ConversationHandler.END

    if target_id == admin.id:
        await msg.reply_text("Can't ban yourself - that's not how moderation works. 🙃")
        return ConversationHandler.END

    target_role = await get_effective_role(target_id)
    if target_role:
        if role_rank(executor_role) <= role_rank(target_role):
            if target_role == "founder":
                await msg.reply_text(
                    f"That's {mention(target_id, target_fname or 'the Founder')}, our Founder - "
                    "banning them is simply not on the table. 👑",
                    parse_mode="HTML",
                )
            else:
                label = ROLE_LABEL.get(target_role, target_role.capitalize())
                await msg.reply_text(
                    f"That's a {cfg.community_name} {label} - they outrank you here, can't ban them."
                )
            return ConversationHandler.END
        await auto_demote(
            ctx.bot,
            target_id,
            target_fname or str(target_id),
            target_role,
            admin.id,
            admin.first_name,
            "ban",
        )

    ctx.user_data["ban_target_id"] = target_id
    ctx.user_data["ban_target_fname"] = target_fname or str(target_id)
    ctx.user_data["ban_reason"] = ban_reason
    ctx.user_data["ban_admin_id"] = admin.id
    ctx.user_data["ban_admin_fname"] = admin.first_name

    target_mention = mention(target_id, target_fname or str(target_id))
    prompt = await msg.reply_text(
        proof.noted_prompt("ban", ban_reason, target_mention),
        parse_mode="HTML",
        reply_markup=proof.keyboard(),
    )
    ctx.user_data["ban_prompt_msg_id"] = prompt.message_id
    ctx.user_data["ban_prompt_chat_id"] = msg.chat.id

    return WAITING_PROOF


# ──────────────────────────── Handlers ──────────────────────────── #

_BAN_CMDS = build_prefixed_filters("tcban") | build_prefixed_filters("tcb")

__handlers__ = [ban_conversation(cmd_ban_start, _BAN_CMDS)]
