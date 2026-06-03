# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""Federation ban command entry point: validates permissions and starts the ban flow."""

from __future__ import annotations

import asyncio
import logging

from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler

from tcbot.modules.helper import decorators, extraction, identity, replies
from tcbot.modules.helper.decorators import resolve_and_check
from tcbot.modules.helper.formatter import mention
from tcbot.modules.helper.workflows.ban_flow import (
    WAITING_PROOF,
    ban_conversation,
    proof,
)
from tcbot.modules.helper.workflows.demote_flow import Demote
from tcbot.utils.prefixes import build_prefixed_filters, parse_cmd_args

log = logging.getLogger(__name__)

# ──────────────── User-facing reply constants ──────────────────── #

_ERR_REASON_REQUIRED = "A reason is required - /tcban <target> <reason>."


# ────────────────────── Module & Help Message ───────────────────── #

__module_name__ = "Ban"
__help_text__ = (
    "Issues a <b>federation-wide ban</b> on a user, applied across every connected "
    "group at once. Auto-demotes staff targets and stores proof with the ban record."
)

__help_sections__: list[tuple[str, str]] = [
    (
        replies.SEC_COMMANDS,
        "<code>/tcban</code> (alias: <code>/tcb</code>)",
    ),
    (
        replies.SEC_WHO,
        replies.PERM_DEV_ABOVE,
    ),
    (
        replies.SEC_WHERE,
        replies.CONTEXT_EXEC_OR_GROUP,
    ),
    (
        replies.SEC_WHAT,
        "Issues a <b>federation-wide ban</b> on the target, applied across all connected "
        "groups automatically. A reason is required - provide it directly after the target.\n\n"
        "After the command, the bot walks you through the proof step: send one or more "
        "photos or videos as evidence. Proof is required and is logged with the ban record "
        "to the federation log channel.\n\n"
        "If the user already has an active ban, the existing record is updated with the new "
        "reason and proof rather than creating a duplicate.\n"
        "If the target holds a federation role (Tester / Developer / Admin), that role is "
        "automatically removed and they are notified by DM before the ban is enforced.",
    ),
    (
        replies.SEC_TARGET,
        replies.TARGET_SYNTAX,
    ),
    (
        replies.SEC_EXAMPLES,
        "<code>/tcban @username spamming in connected groups</code>\n"
        "<code>/tcban 123456789 scamming members</code>\n"
        "Or reply to a message and run <code>/tcb reason here</code>.",
    ),
]


# ────────────────────── Command Ban </tcban> ────────────────────── #


@decorators.ratelimiter(limit=3, period=60)
@decorators.mod_only
@decorators.log_execution
async def cmd_ban_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    """Entry point for the federation ban flow.

    Resolves the target, validates the inline reason, runs identity and role
    checks in parallel, auto-demotes any federation role held by the target, then
    stores ban metadata in ``user_data`` and shows the proof prompt. Returns
    ``WAITING_PROOF`` or ``ConversationHandler.END`` on any failure.
    """
    msg = update.effective_message
    admin = update.effective_user
    raw_args = parse_cmd_args(msg.text)

    has_explicit_target = bool(raw_args) and (
        raw_args[0].lstrip("-").isdigit() or raw_args[0].startswith("@")
    )
    target_id, target_fname = await extraction.extract_target(update, raw_args, ctx.bot)

    ban_reason = " ".join(raw_args[1:] if has_explicit_target else raw_args).strip()

    if not target_id:
        await msg.reply_text(replies.ERR_CANNOT_RESOLVE)
        return ConversationHandler.END

    if not ban_reason:
        await msg.reply_text(_ERR_REASON_REQUIRED)
        return ConversationHandler.END

    # * Identity check + role lookup happen in parallel; both depend only on
    # * already-resolved IDs so there is no need to wait for them sequentially.
    ident, (executor_role, target_role) = await asyncio.gather(
        identity.classify(ctx.bot, admin.id, target_id, target_fname),
        resolve_and_check(msg, admin.id, target_id, min_role="developer"),
    )
    refusal = identity.refuse_message("ban", ident)
    if refusal is not None:
        await msg.reply_text(refusal, parse_mode="HTML")
        return ConversationHandler.END

    if executor_role is None:
        return ConversationHandler.END

    if target_role:
        await Demote.execute(
            ctx.bot,
            target_id,
            target_fname or str(target_id),
            target_role,
            admin.id,
            admin.first_name,
            trigger="ban",
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
