# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Warn executor: record the warning and drive threshold auto-ban."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from telegram import Message, Update

from tcbot import cfg
from tcbot import database as db
from tcbot.modules.helper import keyboards, parse_logmsg, replies
from tcbot.modules.helper.locale import locale_for_update
from tcbot.modules.helper.parse_editmsg import safe_reply
from tcbot.modules.helper.parse_link import message_link
from tcbot.modules.helper.workflows.proof_flow import upload_proof
from tcbot.modules.helper.workflows.warning_flow.autoban import _execute_warn_auto_ban
from tcbot.utils.formatter import user_ref
from tcbot.utils.i18n import Safe, t
from tcbot.utils.logger import get_logger
from tcbot.utils.time_and_date import utc_now

if TYPE_CHECKING:
    from telegram.ext import ContextTypes

log = get_logger(__name__)


async def execute_warn(
    update: Update,
    ctx: ContextTypes.DEFAULT_TYPE,
    target_id: int,
    target_name: str,
    reason_text: str,
    proof_msgs: list[Message] | None = None,
) -> None:
    """Issue a warning and auto-ban the target if a warn threshold is reached.

    Two thresholds can trigger an automatic federation ban:

    1. **Per-group threshold** (``cfg.warn_limit``): fires when a user's warn count
       in the *current* group reaches or exceeds the configured limit. Uses
       ``>=`` so that a retry after a total enforcement failure still fires:
       warns are cleared only after successful enforcement, so a 0/N fan-out
       leaves the count at the limit and the next warn must re-drive the ban
       instead of wedging at limit+1. The ``already_banned`` guard in the
       auto-ban helper skips re-creation when the record already exists.

    2. **Federation-wide threshold** (``cfg.fed_warn_limit``, default 0 = off):
       fires when the user's total warns *across all groups* reach or exceed the
       configured value, even if no single group has hit its per-group limit.
       This closes the evasion path of spreading thin warns across many groups.

    In both cases a non-staff user is banned from all active federation
    groups. A target holding a federation role is demoted first and then
    exempted from the auto-ban (staff are never auto-banned via warnings);
    the warn itself is still recorded. When ``cfg.fed_warn_limit`` is 0
    only the per-group threshold applies (backward-compatible default).
    """
    msg = update.effective_message
    if msg is None:
        return
    chat = update.effective_chat
    if chat is None:
        return
    chat_id = chat.id
    chat_title = chat.title or str(chat_id)
    admin = update.effective_user
    if admin is None:
        return
    admin_id = admin.id
    admin_fname = admin.first_name
    lc, lt = cfg.logs
    locale = await locale_for_update(update)

    # * Upload proof concurrently with the warn write: neither depends on the
    # * other, so serial awaits would add a full proof-channel round trip to
    # * every warn with evidence. On a warn-write failure the upload is
    # * cancelled so the failure reply stays immediate.
    proof_task: asyncio.Task[int | None] | None = None
    pc, pt = cfg.proofs
    if proof_msgs:
        proof_caption = parse_logmsg.proof_caption_new(
            target_id, admin_id, admin_fname, utc_now()
        )
        proof_task = asyncio.create_task(
            upload_proof(ctx.bot, proof_msgs, proof_caption, pc, pt)
        )

    warn_limit = cfg.warn_limit
    # * Fail closed with a retry reply: without the stored warn the
    # * threshold check below is meaningless, and the conversation ends
    # * silently otherwise (the caller clears state and returns END).
    try:
        count = await db.warns_db.add_warn(target_id, reason_text, admin_id, chat_id)
    except Exception:
        if proof_task is not None and not proof_task.done():
            proof_task.cancel()
            await asyncio.gather(proof_task, return_exceptions=True)
        log.exception(
            "add_warn DB write failed for target=%d chat=%d", target_id, chat_id
        )
        await safe_reply(
            msg,
            replies.err_db_retry(locale, plain=True),
            log_label="execute_warn DB-fail",
            parse_mode=None,
        )
        return

    proof_link: str | None = None
    warn_proof_id: int | None = None
    if proof_task is not None:
        try:
            warn_proof_id = await proof_task
        except asyncio.CancelledError:
            proof_task.cancel()
            raise
        except Exception:
            log.warning("Warn proof upload skipped for target=%d", target_id)
            warn_proof_id = None
        if warn_proof_id:
            proof_link = message_link(pc, warn_proof_id, pt)

    proof_kb = keyboards.action_proof_kb(target_id, proof_link)
    log_text = parse_logmsg.warn_log(
        target_id,
        target_name,
        admin_id,
        admin_fname,
        reason_text,
        count,
        warn_limit,
        chat_id,
        chat_title,
    )

    # * "per_group": per-chat warn_limit reached for this group.
    # * "fed_global": federation-wide FED_WARN_LIMIT reached across all groups.
    # * None: below both thresholds; issue a plain warning only.
    #
    # * Per-group uses >= (not ==) so that a retry after a total enforcement
    # * failure still fires: warns are cleared only after successful
    # * enforcement, so a 0/N fan-out leaves the count at the limit and the
    # * next warn must re-drive the ban instead of wedging at limit+1 with
    # * no recovery path. A concurrent double-fire is safe: the auto-ban
    # * helper skips creation when an active ban already exists, and any
    # * duplicate active records are cleaned by deactivate_all_active_bans
    # * on unban.
    # * Federation-wide uses >= because the aggregation is a separate DB read
    # * and has no atomicity guarantee across chat boundaries; >= ensures no
    # * trigger is missed, and the already_banned guard below prevents double bans.
    auto_ban_trigger: str | None = None
    fed_count: int = 0

    if count >= warn_limit:
        auto_ban_trigger = "per_group"
    else:
        fed_limit = cfg.fed_warn_limit
        if fed_limit > 0:
            # * The warn above is already recorded; a failed aggregate read
            # * must not end the conversation silently. Report the recorded
            # * warn honestly and leave the federation-wide check to a retry.
            try:
                fed_count = await db.warns_db.federation_warn_count(target_id)
            except Exception:
                log.exception("federation_warn_count failed for target=%d", target_id)
                await safe_reply(
                    msg,
                    t(
                        "warnings.fed_fail.body",
                        locale,
                        user=Safe(user_ref(target_id, target_name)),
                        count=count,
                        limit=warn_limit,
                        reason=reason_text,
                    ),
                    log_label="execute_warn fed-count-fail",
                    reply_markup=proof_kb,
                )
                return
            if fed_count >= fed_limit:
                auto_ban_trigger = "fed_global"

    if auto_ban_trigger is not None:
        await _execute_warn_auto_ban(
            ctx.bot,
            msg,
            target_id,
            target_name,
            admin_id,
            admin_fname,
            reason_text,
            count,
            warn_limit,
            fed_count,
            auto_ban_trigger,
            proof_kb,
            chat_id,
            lc,
            lt,
            log_text,
            locale,
            warn_proof_id,
        )
    else:
        # * Log channel post and user reply are independent; run in parallel.
        results2 = await asyncio.gather(
            ctx.bot.send_message(
                lc,
                log_text,
                parse_mode="MarkdownV2",
                message_thread_id=lt,
                reply_markup=proof_kb,
            ),
            msg.reply_text(
                t(
                    "warnings.issued.body",
                    locale,
                    user=Safe(user_ref(target_id, target_name)),
                    count=count,
                    limit=warn_limit,
                    reason=reason_text,
                ),
                parse_mode="MarkdownV2",
                reply_markup=proof_kb,
            ),
            return_exceptions=True,
        )
        if isinstance(results2[0], BaseException):
            log.error("Warn log send failed: %s", results2[0])
