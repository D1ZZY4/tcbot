# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Unmute executor: restore send permissions across connected groups."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from telegram import ChatPermissions, Update

from tcbot import database as db
from tcbot.modules.helper import parse_logmsg, replies
from tcbot.modules.helper.parse_editmsg import safe_reply
from tcbot.modules.helper.workflows import muting_flow as _flow
from tcbot.utils.dispatch import count_transient_errors, fan_out
from tcbot.utils.formatter import user_ref
from tcbot.utils.i18n import Safe, t
from tcbot.utils.logger import get_logger

if TYPE_CHECKING:
    from telegram.ext import ContextTypes

log = get_logger(__name__)


async def execute_unmute(
    update: Update,
    ctx: ContextTypes.DEFAULT_TYPE,
    target_id: int,
    target_name: str,
) -> None:
    """Restore full send permissions across all connected groups.

    Guards against issuing a federation-wide unrestrict when no active mute
    record exists, mirroring the ``get_active_ban`` guard in ``execute_unban``.
    """
    msg = update.effective_message
    admin = update.effective_user
    if msg is None or admin is None:
        return
    locale = await _flow.locale_for_update(update)

    # * Guard: only proceed if an active mute record exists. Without this
    # * check the executor would fan unrestricts to all connected groups
    # * even for a no-op, reporting a misleading success. A failed read
    # * fails closed with a retry reply instead of refusing a real unmute.
    try:
        active_mute = await db.mutes_db.get_active_mute(target_id)
    except Exception:
        log.exception("get_active_mute failed for target=%d", target_id)
        await safe_reply(
            msg,
            replies.err_db_retry(locale, plain=True),
            log_label="execute_unmute DB-fail",
            parse_mode=None,
        )
        return
    if active_mute is None:
        await safe_reply(
            msg,
            t(
                "muting.note.no_mute",
                locale,
                user=Safe(user_ref(target_id, target_name)),
            ),
            log_label="execute_unmute no-mute",
        )
        return

    full_perms = ChatPermissions(
        can_send_messages=True,
        can_send_polls=True,
        can_send_other_messages=True,
        can_add_web_page_previews=True,
        can_change_info=False,
        can_invite_users=True,
        can_pin_messages=False,
    )

    # * Fail closed like _execute_mute: a groups-fetch outage aborts before
    # * anything is touched, so the active record stays and a retry works.
    try:
        groups = await db.groups_db.active_groups()
    except Exception:
        log.exception("active_groups failed during unmute of %d", target_id)
        await safe_reply(
            msg,
            replies.err_db_retry(locale, plain=True),
            log_label="execute_unmute groups-fail",
            parse_mode=None,
        )
        return
    # * Connected groups plus primaries (single merge owner in groups_db).
    groups = db.groups_db.with_primary_groups(
        groups, (_flow.cfg.main_group, _flow.cfg.exec_group)
    )
    results = await fan_out(
        [
            ctx.bot.restrict_chat_member(
                grp.get("chat_id", 0),
                target_id,
                permissions=full_perms,
            )
            for grp in groups
        ]
    )
    failed = count_transient_errors(results)
    if failed:
        log.error(
            "Unmute fan-out had %d/%d transient failures for target=%d",
            failed,
            len(groups),
            target_id,
        )

    lc, lt = _flow.cfg.logs
    log_text = parse_logmsg.unmute_log(
        target_id,
        target_name,
        admin.id,
        admin.first_name,
    )

    reply = t(
        "muting.unmute.body",
        locale,
        user=Safe(user_ref(target_id, target_name)),
        done=len(groups) - failed,
        total=len(groups),
    )

    # * Clear the active mute record BEFORE announcing: the reply below
    # * claims the user is restored, which is only true once the record is
    # * gone (a later /tcmute or /check reads it). A failed clear aborts
    # * with a retry reply instead of a false success.
    try:
        await db.mutes_db.clear_active_mute(target_id)
    except Exception:
        log.exception("clear_active_mute failed for target=%d", target_id)
        await safe_reply(
            msg,
            replies.err_db_retry(locale, plain=True),
            log_label="execute_unmute clear-failed",
            parse_mode=None,
        )
        return
    if lc:
        results2 = await asyncio.gather(
            ctx.bot.send_message(
                lc, log_text, parse_mode="MarkdownV2", message_thread_id=lt
            ),
            msg.reply_text(reply, parse_mode="MarkdownV2"),
            return_exceptions=True,
        )
        if isinstance(results2[0], BaseException):
            log.error("Unmute log send failed: %s", results2[0])
        if isinstance(results2[1], BaseException):
            log.debug("execute_unmute reply failed: %s", results2[1])
    else:
        try:
            await msg.reply_text(reply, parse_mode="MarkdownV2")
        except Exception as exc:
            log.debug("execute_unmute no-log reply failed: %s", exc)
