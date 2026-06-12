# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Studio

"""Unban flow - invoked directly by the unban command."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from tcbot import cfg
from tcbot import database as db
from tcbot.modules.helper import parse_logmsg
from tcbot.modules.helper.formatter import code, mention
from tcbot.utils.dispatch import count_errors, fan_out

if TYPE_CHECKING:
    from telegram import Update
    from telegram.ext import ContextTypes

log = logging.getLogger(__name__)


# ───────────────────────── Unban executor ───────────────────────── #


async def execute_unban(
    update: Update,
    ctx: ContextTypes.DEFAULT_TYPE,
    target_id: int,
    target_fname: str,
) -> None:
    """Lift a federation ban: deactivate the DB record and unban across all connected groups.

    Fetches the active ban, runs ``deactivate_ban`` and ``active_groups`` in parallel,
    fans out ``unban_chat_member`` across every group, then sends the log and reply
    concurrently. Replies inline if no active ban is found.
    """
    msg = update.effective_message
    admin = update.effective_user

    ban = await db.bans_db.get_active_ban(target_id)
    if not ban:
        try:
            await msg.reply_text(
                f"{mention(target_id, target_fname)} - {code(str(target_id))} "
                f"has no active federation ban.",
                parse_mode="HTML",
            )
        except Exception as exc:
            log.debug("Unban no-record reply failed for user %d: %s", target_id, exc)
        return

    ban_id = ban["ban_id"]

    # * deactivate ban and fetch active groups in parallel
    deactivate_r, groups = await asyncio.gather(
        db.bans_db.deactivate_ban(ban_id),
        db.groups_db.active_groups(),
        return_exceptions=True,
    )
    if isinstance(deactivate_r, BaseException):
        log.error(
            "deactivate_ban failed for ban_id=%s user=%d: %s",
            ban_id,
            target_id,
            deactivate_r,
        )
    if isinstance(groups, BaseException):
        log.error("active_groups failed during unban of %d: %s", target_id, groups)
        groups = []

    # * unban from all groups - semaphore-bounded for rate safety
    results = await fan_out(
        [
            ctx.bot.unban_chat_member(grp["chat_id"], target_id, only_if_banned=True)
            for grp in groups
        ]
    )
    failed = count_errors(results)

    lc, lt = cfg.logs
    log_text = parse_logmsg.unban_log(
        target_id,
        target_fname,
        admin.id,
        admin.first_name,
        ban_id,
    )

    # * send log and reply in parallel
    log_r, reply_r = await asyncio.gather(
        ctx.bot.send_message(lc, log_text, parse_mode="HTML", message_thread_id=lt),
        msg.reply_text(
            f"{mention(target_id, target_fname)} - {code(str(target_id))} "
            f"has been unbanned - "
            f"removed from {len(groups) - failed}/{len(groups)} groups.",
            parse_mode="HTML",
        ),
        return_exceptions=True,
    )
    if isinstance(log_r, BaseException):
        log.error("Unban log send failed for user %d: %s", target_id, log_r)
    if isinstance(reply_r, BaseException):
        log.debug("Unban reply failed for user %d: %s", target_id, reply_r)
