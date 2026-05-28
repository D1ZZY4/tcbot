# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""Broadcast command handler – sends a message to all connected groups."""

from __future__ import annotations

import asyncio
import logging

from telegram import Update
from telegram.ext import ContextTypes, MessageHandler

from tcbot import cfg
from tcbot import database as db
from tcbot.modules.helper import decorators, parse_logmsg
from tcbot.modules.helper.formatter import code
from tcbot.utils.dispatch import fan_out
from tcbot.utils.prefixes import build_prefixed_filters, parse_cmd_args

log = logging.getLogger(__name__)


# ────────────────────── Module & Help Message ───────────────────── #

__module_name__ = "Broadcast"
__help_text__ = (
    "<b>Commands & Aliases</b>\n"
    "<code>/tcbroadcast</code> (alias: <code>/bc</code>)\n\n"
    "<b>Who can use it</b>\n"
    "TC Staff (Admin and above).\n\n"
    "<b>Where to use it</b>\n"
    "Exec group or bot PM.\n\n"
    "<b>What it does</b>\n"
    f"Sends a message to every group currently connected to {cfg.community_name}. "
    "You can compose the message in two ways:\n"
    "- Type the message directly after the command (HTML formatting is supported).\n"
    "- Reply to an existing message with <code>/bc</code> to forward that message to all groups.\n\n"
    "When the broadcast is complete, the bot shows a summary of how many groups received the "
    "message and how many deliveries failed, and posts a log entry to the federation logs channel.\n\n"
    "<b>Examples</b>\n"
    "<code>/tcbroadcast Reminder: please review the community rules before posting.</code>\n"
    "<code>/bc <b>Event tonight</b> - join us in the main group at 8 PM UTC.</code>\n"
    "Or reply to any message and run <code>/bc</code> to forward it to all groups."
)


# ──────────────── Command Broadcast </tcbroadcast> ──────────────── #


@decorators.ratelimiter(limit=3, period=60)
@decorators.staff_only
@decorators.log_execution
async def cmd_broadcast(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    admin = update.effective_user

    args = parse_cmd_args(msg.text)
    broadcast_text: str | None = " ".join(args).strip() if args else None

    has_reply = bool(msg.reply_to_message)
    if not broadcast_text and not has_reply:
        await msg.reply_text(
            "Please provide a message to broadcast, or reply to a message."
        )
        return

    groups = await db.groups_db.active_groups()
    if not groups:
        await msg.reply_text("No connected groups.")
        return

    status = await msg.reply_text(f"Broadcasting to {len(groups)} group(s)...")

    # * Build per-group send coroutines, then fan out with semaphore limiting
    async def _send_one(grp: dict) -> None:
        if has_reply and msg.reply_to_message:
            await msg.reply_to_message.forward(grp["chat_id"])
        elif broadcast_text:
            await ctx.bot.send_message(
                grp["chat_id"], broadcast_text, parse_mode="HTML"
            )

    results = await fan_out([_send_one(grp) for grp in groups])
    success = sum(1 for r in results if not isinstance(r, BaseException))
    failed = len(results) - success

    for grp, r in zip(groups, results):
        if isinstance(r, BaseException):
            log.warning("Broadcast failed for %d: %s", grp["chat_id"], r)

    if broadcast_text:
        preview = broadcast_text
    elif msg.reply_to_message:
        preview = msg.reply_to_message.text or "media"
    else:
        preview = ""
    lc, lt = cfg.logs

    # * send log and update status message in parallel
    await asyncio.gather(
        ctx.bot.send_message(
            lc,
            parse_logmsg.broadcast_log(
                admin.id, admin.first_name, preview, success, failed
            ),
            parse_mode="HTML",
            message_thread_id=lt,
        ),
        status.edit_text(
            f"Broadcast sent to {code(str(success))} groups. Failed: {code(str(failed))}.",
            parse_mode="HTML",
        ),
        return_exceptions=True,
    )


# ──────────────────────────── Handlers ──────────────────────────── #

_BROADCAST_CMDS = build_prefixed_filters("tcbroadcast") | build_prefixed_filters("bc")

__handlers__ = [MessageHandler(_BROADCAST_CMDS, cmd_broadcast)]
