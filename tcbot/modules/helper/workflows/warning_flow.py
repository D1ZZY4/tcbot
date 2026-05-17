# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""
Warning conversation flow helpers - per-group warning tracking
"""

from __future__ import annotations

import asyncio
import logging

from telegram import Update
from telegram.ext import ContextTypes

from tcbot import cfg, database as db
from tcbot.modules.helper import parse_logmsg
from tcbot.modules.helper.formatter import code, mention

log = logging.getLogger(__name__)

WARN_LIMIT = 3


async def execute_warn(
    update: Update,
    ctx: ContextTypes.DEFAULT_TYPE,
    target_id: int,
    target_name: str,
    reason: str,
    proof_desc: str | None = None,
) -> None:
    msg = update.effective_message
    chat_id = update.effective_chat.id
    admin_id = update.effective_user.id

    count = await db.warns_db.add_warn(target_id, reason, admin_id, chat_id)
    proof_line  = f"\nProof: {proof_desc}" if proof_desc else ""
    chat_title  = update.effective_chat.title or str(chat_id)
    admin_fname = update.effective_user.first_name
    lc, lt      = cfg.logs
    log_text    = parse_logmsg.warn_log(
        target_id, target_name, admin_id, admin_fname,
        reason, count, WARN_LIMIT, chat_id, chat_title,
    )

    if count >= WARN_LIMIT:
        ## clear warns + ban + federation log — all in parallel
        results = await asyncio.gather(
            db.warns_db.clear_warns(target_id, chat_id),
            ctx.bot.ban_chat_member(chat_id, target_id),
            ctx.bot.send_message(lc, log_text, parse_mode="HTML", message_thread_id=lt),
            return_exceptions=True,
        )
        if isinstance(results[2], BaseException):
            log.error("Warn log send failed: %s", results[2])
        ban_result = results[1]
        if not isinstance(ban_result, BaseException):
            await msg.reply_text(
                f"{mention(target_id, target_name)} hit {WARN_LIMIT} warnings "
                f"and has been banned from this group.{proof_line}",
                parse_mode="HTML",
            )
        else:
            log.error("Auto-ban on warn limit failed: %s", ban_result)
            await msg.reply_text(
                f"{mention(target_id, target_name)} hit {WARN_LIMIT} warnings "
                f"but auto-ban failed — please ban them manually.{proof_line}",
                parse_mode="HTML",
            )
    else:
        ## federation log + reply in parallel
        results2 = await asyncio.gather(
            ctx.bot.send_message(lc, log_text, parse_mode="HTML", message_thread_id=lt),
            msg.reply_text(
                f"{mention(target_id, target_name)} has been warned "
                f"({count}/{WARN_LIMIT}) — {reason}{proof_line}",
                parse_mode="HTML",
            ),
            return_exceptions=True,
        )
        if isinstance(results2[0], BaseException):
            log.error("Warn log send failed: %s", results2[0])


async def execute_unwarn(
    update: Update,
    ctx: ContextTypes.DEFAULT_TYPE,
    target_id: int,
    target_name: str,
) -> None:
    msg = update.effective_message
    chat_id = update.effective_chat.id

    count = await db.warns_db.warn_count(target_id, chat_id)
    if count == 0:
        await msg.reply_text(
            f"{mention(target_id, target_name)} {code(str(target_id))} has no warnings in this group.",
            parse_mode="HTML",
        )
        return

    new_count   = max(count - 1, 0)
    chat_title  = update.effective_chat.title or str(chat_id)
    admin       = update.effective_user
    lc, lt      = cfg.logs
    log_text    = parse_logmsg.unwarn_log(
        target_id, target_name, admin.id, admin.first_name,
        new_count, WARN_LIMIT, chat_id, chat_title,
    )
    ## remove warn + send log + reply in parallel
    results = await asyncio.gather(
        db.warns_db.remove_last_warn(target_id, chat_id),
        ctx.bot.send_message(lc, log_text, parse_mode="HTML", message_thread_id=lt),
        msg.reply_text(
            f"One warning removed from {mention(target_id, target_name)}. "
            f"They're now at {new_count}/{WARN_LIMIT}.",
            parse_mode="HTML",
        ),
        return_exceptions=True,
    )
    if isinstance(results[1], BaseException):
        log.error("Unwarn log send failed: %s", results[1])


async def execute_warnlist(
    update: Update,
    ctx: ContextTypes.DEFAULT_TYPE,
    target_id: int,
    target_name: str,
) -> None:
    msg = update.effective_message
    chat_id = update.effective_chat.id

    warns = await db.warns_db.get_warns(target_id, chat_id)
    count = len(warns)

    if count == 0:
        await msg.reply_text(
            f"{mention(target_id, target_name)} {code(str(target_id))} has no warnings in this group.",
            parse_mode="HTML",
        )
        return

    lines = [
        f"{mention(target_id, target_name)} has {count}/{WARN_LIMIT} warnings:\n"
    ]
    for i, w in enumerate(warns, 1):
        reason = w.get("reason", "No reason")
        lines.append(f"  {i}. {reason}")

    await msg.reply_text("\n".join(lines), parse_mode="HTML")


async def execute_resetwarns(
    update: Update,
    ctx: ContextTypes.DEFAULT_TYPE,
    target_id: int,
    target_name: str,
) -> None:
    msg = update.effective_message
    chat_id = update.effective_chat.id

    removed = await db.warns_db.clear_warns(target_id, chat_id)
    if removed == 0:
        await msg.reply_text(
            f"{mention(target_id, target_name)} {code(str(target_id))} has no warnings to clear.",
            parse_mode="HTML",
        )
        return

    await msg.reply_text(
        f"All {removed} warning(s) cleared for {mention(target_id, target_name)}. Clean slate.",
        parse_mode="HTML",
    )
