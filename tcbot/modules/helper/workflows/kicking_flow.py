# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Studio

"""Kick executor + conversation factory."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from tcbot import cfg
from tcbot import database as db
from tcbot.modules.helper import parse_logmsg, replies
from tcbot.modules.helper.formatter import code, esc, mention, proof_line
from tcbot.modules.helper.workflows.proof_flow import BuildProof
from tcbot.modules.helper.workflows.reason_flow import BuildReason, build_modaction_conv

if TYPE_CHECKING:
    from collections.abc import Callable

    from telegram import Update
    from telegram.ext import ContextTypes
    from telegram.ext.filters import BaseFilter

log = logging.getLogger(__name__)

# ──────────────── User-facing reply constants ──────────────────── #

_MSG_REJOIN_ALLOWED = "They can rejoin via invite link."

# * Per-action BuildReason and BuildProof instances; imported by kicking.py
reason = BuildReason("kick")
proof = BuildProof("kick")


# ────────────────────────── Kick executor ───────────────────────── #


async def execute_kick(
    update: Update,
    ctx: ContextTypes.DEFAULT_TYPE,
    target_id: int,
    target_name: str,
    reason_text: str,
    proof_desc: str | None = None,
) -> None:
    """Kick (ban then immediately unban) a user from the current group."""
    msg = update.effective_message
    chat_id = update.effective_chat.id
    admin_id = update.effective_user.id

    try:
        await ctx.bot.ban_chat_member(chat_id, target_id)
        proof_suffix = proof_line(proof_desc)
        chat_title = update.effective_chat.title or str(chat_id)
        admin_fname = update.effective_user.first_name
        lc, lt = cfg.logs
        log_text = parse_logmsg.kick_log(
            target_id,
            target_name,
            admin_id,
            admin_fname,
            reason_text,
            chat_id,
            chat_title,
        )
        # * unban + log_kick + federation log + reply all run in parallel
        results = await asyncio.gather(
            ctx.bot.unban_chat_member(chat_id, target_id, only_if_banned=True),
            db.kicks_db.log_kick(target_id, chat_id, reason_text, admin_id),
            ctx.bot.send_message(lc, log_text, parse_mode="HTML", message_thread_id=lt),
            msg.reply_text(
                f"{mention(target_id, target_name)} - {code(str(target_id))} has been kicked.\n"
                f"Reason: {esc(reason_text)}{proof_suffix}\n"
                f"{_MSG_REJOIN_ALLOWED}",
                parse_mode="HTML",
            ),
            return_exceptions=True,
        )
        if isinstance(results[1], BaseException):
            log.error(
                "log_kick DB write failed for target=%d: %s", target_id, results[1]
            )
        if isinstance(results[2], BaseException):
            log.error("Kick log send failed: %s", results[2])
    except Exception as exc:
        log.exception("Kick failed for %s in %s", target_id, chat_id)
        try:
            await msg.reply_text(
                f"Couldn't kick {mention(target_id, target_name)}: {esc(exc)}",
                parse_mode="HTML",
            )
        except Exception as reply_exc:
            log.debug("Kick error reply failed: %s", reply_exc)


# ──────────────────────── Executor adapter ──────────────────────── #


async def _exec_kick(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Pop kick data from user_data and call execute_kick."""
    target_id = ctx.user_data.pop("kick_target_id", 0)
    target_name = ctx.user_data.pop("kick_target_name", "")
    reason_text = ctx.user_data.pop("kick_reason", replies.NO_REASON)
    proof_desc = ctx.user_data.pop("kick_proof_desc", None)
    ctx.user_data.pop("kick_extra_info", None)
    await execute_kick(
        update, ctx, target_id, target_name, reason_text, proof_desc=proof_desc
    )


# ─────────────────── ConversationHandler factory ────────────────── #


def kick_conversation(entry_fn: Callable[..., Any], entry_filter: BaseFilter) -> object:
    """Return the kick ConversationHandler via the central reason_flow factory."""
    return build_modaction_conv(reason, proof, entry_fn, _exec_kick, entry_filter)
