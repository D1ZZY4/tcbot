# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Studio

"""Group kick command entry point: validates permissions and delegates to kicking_flow."""

from __future__ import annotations

import asyncio
import logging

from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler

from tcbot.modules.helper import decorators, extraction, identity, replies
from tcbot.modules.helper.decorators import resolve_and_check
from tcbot.modules.helper.formatter import mention
from tcbot.modules.helper.workflows.demote_flow import Demote
from tcbot.modules.helper.workflows.kicking_flow import kick_conversation, proof, reason
from tcbot.modules.helper.workflows.reason_flow import (
    WAITING_PROOF,
    WAITING_REASON,
    parse_inline_reason,
)
from tcbot.utils.prefixes import build_prefixed_filters, parse_cmd_args

log = logging.getLogger(__name__)

# ─────────────────────── Rate-limiter constants ──────────────────── #
_RL_PERIOD_S: int = 60
_RL_LIMIT: int = 5


# ────────────────────── Module & Help Message ───────────────────── #

__module_name__ = "Kick"
__help_text__ = (
    "Removes a user from the <b>current group only</b>. Federation roles are auto-removed "
    "if the target is staff."
)

__help_sections__: list[tuple[str, str]] = [
    (
        replies.SEC_COMMANDS,
        "<code>/tckick</code> (alias: <code>/tck</code>)",
    ),
    (
        replies.SEC_WHO,
        replies.PERM_TESTER_ABOVE,
    ),
    (
        replies.SEC_WHERE,
        replies.WHERE_CONNECTED_GROUP,
    ),
    (
        replies.SEC_WHAT,
        "Removes a user from the <b>current group only</b>. This is not a federation-wide "
        "action; the user can rejoin via an invite link unless they are separately "
        "federation-banned.\n\n"
        "If the target holds a federation role (Tester / Developer / Admin), that role is "
        "automatically removed and they are notified by DM. A log entry is posted to the "
        "federation logs channel.",
    ),
    (
        "Flow",
        "1. Run <code>/tckick</code> with the target (and optional inline reason).\n"
        "2. If no reason was given, the bot asks: reply with text or tap <b>Skip</b>.\n"
        "3. The bot asks for proof: send a photo/video or tap <b>Skip</b>.",
    ),
    (
        replies.SEC_TARGET,
        replies.TARGET_SYNTAX,
    ),
    (
        replies.SEC_EXAMPLES,
        "<code>/tckick @username being disruptive</code>: reason inline\n"
        "<code>/tck 123456789</code>: bot will ask for reason\n"
        "Or reply to a message and run <code>/tck</code>.",
    ),
]


# ───────────────────── Command Kick </tckick> ───────────────────── #


@decorators.ratelimiter(limit=_RL_LIMIT, period=_RL_PERIOD_S)
@decorators.basic_mod_only
@decorators.log_execution
async def cmd_kick(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    """Entry point for the kick flow.

    Resolves the target, runs identity and role checks in parallel, auto-demotes
    any federation role, then either executes an immediate kick (with inline
    reason) or opens the reason/proof conversation. Returns
    ``ConversationHandler.END`` on validation failure.
    """
    msg = update.effective_message
    admin = update.effective_user

    args = parse_cmd_args(msg.text)
    has_explicit_target = bool(args) and (
        args[0].lstrip("-").isdigit() or args[0].startswith("@")
    )
    target_id, target_name = await extraction.extract_target(update, args, ctx.bot)

    inline_reason = parse_inline_reason(args, has_explicit_target)

    if not target_id:
        await msg.reply_text(replies.ERR_CANT_FIND_USER)
        return ConversationHandler.END

    ident, (executor_role, target_role) = await asyncio.gather(
        identity.classify(ctx.bot, admin.id, target_id, target_name),
        resolve_and_check(msg, admin.id, target_id, min_role="tester"),
    )
    refusal = identity.refuse_message("kick", ident)
    if refusal is not None:
        await msg.reply_text(refusal, parse_mode="HTML")
        return ConversationHandler.END

    if executor_role is None:
        return ConversationHandler.END

    if target_role:
        await Demote.execute(
            ctx.bot,
            target_id,
            target_name or str(target_id),
            target_role,
            admin.id,
            admin.first_name,
            trigger="kick",
        )

    ctx.user_data.update(
        {
            "kick_target_id": target_id,
            "kick_target_name": target_name or str(target_id),
            "kick_proof_desc": None,
        }
    )

    target_mention = mention(target_id, target_name or str(target_id))

    if inline_reason:
        ctx.user_data["kick_reason"] = inline_reason
        await msg.reply_text(
            proof.noted_prompt("kick", inline_reason, target_mention),
            parse_mode="HTML",
            reply_markup=proof.keyboard(),
        )
        return WAITING_PROOF

    await msg.reply_text(
        reason.prompt(target_mention, "kick"),
        parse_mode="HTML",
        reply_markup=reason.keyboard(),
    )
    return WAITING_REASON


# ──────────────────────────── Handlers ──────────────────────────── #

_KICK_CMDS = build_prefixed_filters("tckick") | build_prefixed_filters("tck")

__handlers__ = [kick_conversation(cmd_kick, _KICK_CMDS)]
