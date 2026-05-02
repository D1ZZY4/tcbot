# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""Maintenance commands – leaveall and cleanup."""
from __future__ import annotations

import asyncio
import logging

from telegram import Update
from telegram.ext import ContextTypes, MessageHandler

from tcbot import database as db
from tcbot.config import cfg
from tcbot.modules.helper import decorators, parse_logmsg
from tcbot.modules.helper.formatter import code
from tcbot.utils.prefixes import build_prefixed_filters

log = logging.getLogger(__name__)

__module_name__ = "Cleanup"
__help_text__ = (
    "<code>/leaveall</code> – leave all affiliated groups and deactivate them (owner only).\n"
    "Aliases: <code>/exitall</code>, <code>/tcleave</code>\n\n"
    "<code>/cleanup</code> – remove defunct groups the bot was kicked from (TC staff only).\n"
    "Aliases: <code>/purge</code>, <code>/tcclean</code>"
)


@decorators.owner_only
async def cmd_leaveall(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    admin = update.effective_user
    groups = await db.groups_db.active_groups()
    if not groups:
        await update.effective_message.reply_text("No affiliated groups.")
        return

    status = await update.effective_message.reply_text(f"Leaving {len(groups)} groups...")
    left, failed = 0, 0
    lc, lt = cfg.logs

    for grp in groups:
        try:
            await ctx.bot.leave_chat(grp["chat_id"])
            await db.groups_db.deactivate_group(grp["chat_id"])
            left += 1
            ## Log each departure
            try:
                await ctx.bot.send_message(
                    lc,
                    parse_logmsg.group_disconnected_log(
                        grp["chat_id"], grp["title"], admin.id, admin.first_name,
                    ),
                    parse_mode="HTML",
                    message_thread_id=lt,
                )
            except Exception:
                pass
        except Exception:
            failed += 1
        await asyncio.sleep(0.05)

    try:
        await status.edit_text(
            f"Left {code(str(left))} groups. Failed to leave {code(str(failed))} groups.",
            parse_mode="HTML",
        )
    except Exception:
        pass


@decorators.staff_only
async def cmd_cleanup(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    groups = await db.groups_db.active_groups()
    removed = 0

    for grp in groups:
        try:
            bot_member = await ctx.bot.get_chat_member(grp["chat_id"], ctx.bot.id)
            if bot_member.status in ("left", "kicked"):
                await db.groups_db.deactivate_group(grp["chat_id"])
                removed += 1
        except Exception:
            await db.groups_db.deactivate_group(grp["chat_id"])
            removed += 1

    await update.effective_message.reply_text(
        f"Cleaned up {code(str(removed))} groups that were no longer accessible.",
        parse_mode="HTML",
    )


## Spec aliases: /leaveall, /exitall, /tcleave
_LEAVEALL_FILTER = (
    build_prefixed_filters("leaveall")
    | build_prefixed_filters("exitall")
    | build_prefixed_filters("tcleave")
)
## Spec aliases: /cleanup, /purge, /tcclean
_CLEANUP_FILTER = (
    build_prefixed_filters("cleanup")
    | build_prefixed_filters("purge")
    | build_prefixed_filters("tcclean")
)

__handlers__ = [
    MessageHandler(_LEAVEALL_FILTER, cmd_leaveall),
    MessageHandler(_CLEANUP_FILTER, cmd_cleanup),
]
