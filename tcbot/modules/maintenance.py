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
from tcbot import cfg
from tcbot.modules.helper import decorators, parse_logmsg
from tcbot.modules.helper.formatter import code
from tcbot.utils.prefixes import build_prefixed_filters

log = logging.getLogger(__name__)

__module_name__ = "Cleanup"
__help_text__ = (
    "<b>Commands & Aliases</b>\n"
    "<code>/leaveall</code> — aliases: <code>/exitall</code>, <code>/tcleave</code>\n"
    "<code>/cleanup</code> — aliases: <code>/tcclean</code>, <code>/tcc</code>\n\n"

    "<b>Who can use it</b>\n"
    "<code>/leaveall</code> — Owner only.\n"
    "<code>/cleanup</code> — TC Staff (admins & owner).\n\n"

    "<b>Where to use it</b>\n"
    "Exec group or bot PM.\n\n"

    "<b>What it does</b>\n"
    "<code>/leaveall</code> — makes the bot leave every connected group and marks them all "
    "as disconnected. A log entry is posted for each group. Use with care — this is irreversible "
    "without re-connecting each group manually.\n\n"
    "<code>/cleanup</code> — scans all connected groups and removes any that the bot was "
    "kicked from or can no longer access. Keeps the database clean and the group list accurate.\n\n"

    "<b>Examples</b>\n"
    "<code>/cleanup</code> — run this periodically to remove stale groups.\n"
    "<code>/leaveall</code> — emergency exit from all groups."
)


async def _leave_one(
    bot,
    grp: dict,
    lc: int,
    lt: int | None,
    admin_id: int,
    admin_name: str,
) -> list:
    """Leave one group, deactivate it in DB, and post a disconnection log — all in parallel."""
    return await asyncio.gather(
        bot.leave_chat(grp["chat_id"]),
        db.groups_db.deactivate_group(grp["chat_id"]),
        bot.send_message(
            lc,
            parse_logmsg.group_disconnected_log(
                grp["chat_id"], grp["title"], admin_id, admin_name,
            ),
            parse_mode="HTML",
            message_thread_id=lt,
        ),
        return_exceptions=True,
    )


@decorators.owner_only
async def cmd_leaveall(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    admin  = update.effective_user
    groups = await db.groups_db.active_groups()
    if not groups:
        await update.effective_message.reply_text("No connected groups.")
        return

    status = await update.effective_message.reply_text(f"Leaving {len(groups)} groups...")
    lc, lt = cfg.logs

    ## All groups processed concurrently — no sequential sleep between them
    all_results = await asyncio.gather(
        *(_leave_one(ctx.bot, g, lc, lt, admin.id, admin.first_name) for g in groups),
        return_exceptions=True,
    )

    left = sum(
        1 for r in all_results
        if not isinstance(r, BaseException) and not isinstance(r[0], BaseException)
    )
    failed = len(groups) - left

    try:
        await status.edit_text(
            f"Left {code(str(left))} groups. Failed: {code(str(failed))}.",
            parse_mode="HTML",
        )
    except Exception:
        pass


async def _should_remove(bot, grp: dict) -> bool:
    """Return True if the bot has left or been kicked from the group."""
    try:
        member = await bot.get_chat_member(grp["chat_id"], bot.id)
        return member.status in ("left", "kicked")
    except Exception:
        return True


@decorators.staff_only
async def cmd_cleanup(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    groups = await db.groups_db.active_groups()

    ## Check all groups concurrently — one network round-trip per group, all in parallel
    checks = await asyncio.gather(
        *(_should_remove(ctx.bot, g) for g in groups),
        return_exceptions=True,
    )

    to_remove = [g for g, remove in zip(groups, checks) if remove is True]

    if to_remove:
        await asyncio.gather(
            *(db.groups_db.deactivate_group(g["chat_id"]) for g in to_remove),
        )

    await update.effective_message.reply_text(
        f"Cleaned up {code(str(len(to_remove)))} inaccessible group(s).",
        parse_mode="HTML",
    )


_LEAVEALL_FILTER = (
    build_prefixed_filters("leaveall")
    | build_prefixed_filters("exitall")
    | build_prefixed_filters("tcleave")
)
_CLEANUP_FILTER = (
    build_prefixed_filters("cleanup")
    | build_prefixed_filters("tcclean")
    | build_prefixed_filters("tcc")
)

__handlers__ = [
    MessageHandler(_LEAVEALL_FILTER, cmd_leaveall),
    MessageHandler(_CLEANUP_FILTER, cmd_cleanup),
]
