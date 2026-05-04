# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""Warning flow helpers – per-group warning tracking."""
from __future__ import annotations

import asyncio
import logging

from telegram import Update
from telegram.ext import ContextTypes

from tcbot import database as db
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
    proof_line = f"\nProof: {proof_desc}" if proof_desc else ""

    if count >= WARN_LIMIT:
        ## clear warns + ban run in parallel
        results = await asyncio.gather(
            db.warns_db.clear_warns(target_id, chat_id),
            ctx.bot.ban_chat_member(chat_id, target_id),
            return_exceptions=True,
        )
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
        await msg.reply_text(
            f"{mention(target_id, target_name)} has been warned "
            f"({count}/{WARN_LIMIT}) — {reason}{proof_line}",
            parse_mode="HTML",
        )


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

    new_count = max(count - 1, 0)
    ## remove warn and send reply in parallel
    await asyncio.gather(
        db.warns_db.remove_last_warn(target_id, chat_id),
        msg.reply_text(
            f"One warning removed from {mention(target_id, target_name)}. "
            f"They're now at {new_count}/{WARN_LIMIT}.",
            parse_mode="HTML",
        ),
    )


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
