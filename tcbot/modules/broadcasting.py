# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""Broadcast a message to all affiliated groups."""
from __future__ import annotations

import asyncio
import logging

from telegram import Update
from telegram.ext import ContextTypes, MessageHandler

from tcbot import database as db
from tcbot.config import cfg
from tcbot.modules.helper import decorators, parse_logmsg
from tcbot.modules.helper.formatter import code
from tcbot.utils.prefixes import build_prefixed_filters, parse_cmd_args

log = logging.getLogger(__name__)

__module_name__ = "Broadcast"
__help_text__ = (
    "<code>/tcbroadcast</code> <i>&lt;message&gt;</i> – send a message to all affiliated groups (staff only).\n"
    "Provide text directly or reply to a message to forward it.\n"
    "Aliases: <code>/broadcast</code>, <code>/tcannounce</code>"
)


@decorators.staff_only
async def cmd_broadcast(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    admin = update.effective_user

    ## Determine message content
    args = parse_cmd_args(msg.text)
    broadcast_text: str | None = " ".join(args).strip() if args else None

    has_reply = bool(msg.reply_to_message)
    if not broadcast_text and not has_reply:
        await msg.reply_text("Please provide a message to broadcast, or reply to a message.")
        return

    groups = await db.groups_db.active_groups()
    if not groups:
        await msg.reply_text("No affiliated groups.")
        return

    status = await msg.reply_text(f"Broadcasting to {len(groups)} group(s)...")
    success, failed = 0, 0

    for grp in groups:
        try:
            if has_reply and msg.reply_to_message:
                await msg.reply_to_message.forward(grp["chat_id"])
            elif broadcast_text:
                await ctx.bot.send_message(grp["chat_id"], broadcast_text)
            success += 1
        except Exception as exc:
            log.warning("Broadcast failed for %d: %s", grp["chat_id"], exc)
            failed += 1
        await asyncio.sleep(0.05)

    ## Log to LOG_CHANNEL
    preview = broadcast_text or (msg.reply_to_message.text or "media") if msg.reply_to_message else ""
    lc, lt = cfg.logs
    try:
        await ctx.bot.send_message(
            lc,
            parse_logmsg.broadcast_log(admin.id, admin.first_name, preview, success, failed),
            parse_mode="HTML",
            message_thread_id=lt,
        )
    except Exception as exc:
        log.error("Broadcast log failed: %s", exc)

    try:
        await status.edit_text(
            f"Broadcast sent to {code(str(success))} groups. Failed: {code(str(failed))} groups.",
            parse_mode="HTML",
        )
    except Exception:
        pass


## Spec aliases: /tcbroadcast, /broadcast, /tcannounce
_BROADCAST_FILTER = (
    build_prefixed_filters("tcbroadcast")
    | build_prefixed_filters("broadcast")
    | build_prefixed_filters("tcannounce")
)

__handlers__ = [MessageHandler(_BROADCAST_FILTER, cmd_broadcast)]
