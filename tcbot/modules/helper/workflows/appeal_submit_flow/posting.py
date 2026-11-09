# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Review-card posting for validated appeal submissions."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from telegram.ext import ConversationHandler

from tcbot import database as db
from tcbot.modules.helper import parse_logmsg
from tcbot.modules.helper.keyboards import appeal_review_kb
from tcbot.modules.helper.parse_editmsg import safe_reply
from tcbot.modules.helper.parse_link import message_link
from tcbot.modules.helper.workflows import appeal_submit_flow as flow_pkg
from tcbot.modules.helper.workflows.appeal_submit_flow.gates import (
    _STALE_REVIEW_HOURS,
    WAITING_APPEAL,
    _clear_appeal_state,
)
from tcbot.utils.dispatch import throw_if_cancelled
from tcbot.utils.i18n import t
from tcbot.utils.logger import get_logger

if TYPE_CHECKING:
    from telegram import Message, Update, User
    from telegram.ext import ContextTypes

log = get_logger(__name__)


async def post_appeal(
    update: Update,
    ctx: ContextTypes.DEFAULT_TYPE,
    msg: Message,
    user: User,
    uid: int,
    ban_id: str,
    locale: str | None,
) -> int:
    """Forward a validated appeal and post its dual review cards.

    Returns ``WAITING_APPEAL`` when the review post failed and the user
    may retry in place, or ``ConversationHandler.END`` after a successful
    submission or a lost review race.
    """
    if ctx.user_data is None:
        log.error("ctx.user_data is None in appeal posting")
        return ConversationHandler.END
    appeal_chat, appeal_thread = flow_pkg.cfg.appeals
    appeal_msg_id: int | None = None
    try:
        fwd = await msg.forward(appeal_chat, message_thread_id=appeal_thread)
        appeal_msg_id = fwd.message_id
    except Exception:
        log.exception("Appeal forward failed")

    appeal_link = (
        message_link(appeal_chat, appeal_msg_id, appeal_thread) if appeal_msg_id else ""
    )
    review_text = parse_logmsg.appeal_received_log(
        uid, user.first_name, ban_id, appeal_link
    )
    lc, lt = flow_pkg.cfg.logs

    # * Send review post + log message in parallel. The review card is
    # * posted in both MAIN_GROUP (general) and the APPEALS destination so
    # * either surface stays actionable; the forwarded appeal text
    # * above already lands in APPEALS.
    rv, rv_appeals, sent_log = await asyncio.gather(
        ctx.bot.send_message(
            flow_pkg.cfg.main_group,
            review_text,
            parse_mode="MarkdownV2",
            reply_markup=appeal_review_kb(ban_id),
        ),
        ctx.bot.send_message(
            appeal_chat,
            review_text,
            parse_mode="MarkdownV2",
            message_thread_id=appeal_thread,
            reply_markup=appeal_review_kb(ban_id),
        ),
        ctx.bot.send_message(
            lc,
            parse_logmsg.appeal_submitted_log(
                uid, user.first_name, ban_id, appeal_link
            ),
            parse_mode="MarkdownV2",
            message_thread_id=lt,
        ),
        return_exceptions=True,
    )
    throw_if_cancelled((rv, rv_appeals, sent_log))

    review_msg_id: int | None = (
        rv.message_id if not isinstance(rv, BaseException) else None
    )
    if isinstance(rv, BaseException):
        log.error("Appeal review post failed: %s", rv)

    appeals_review_id: int | None = (
        rv_appeals.message_id if not isinstance(rv_appeals, BaseException) else None
    )
    if isinstance(rv_appeals, BaseException):
        log.error("Appeal review copy to APPEALS failed: %s", rv_appeals)

    appeal_log_sent_id: int | None = (
        sent_log.message_id if not isinstance(sent_log, BaseException) else None
    )
    if isinstance(sent_log, BaseException):
        log.error("Appeal log failed: %s", sent_log)

    # * Claim the pending-review slot atomically before storing anything
    # * else: a concurrent submit for the same ban (another session that
    # * passed the re-check above) must not overwrite the winner and
    # * orphan its review card. The loser deletes its own orphan card
    # * best-effort and tells the user the appeal is already pending.
    claimed = False
    if review_msg_id:
        try:
            claimed = await db.bans_db.set_review_if_absent(ban_id, review_msg_id)
        except Exception:
            log.exception("Appeal claim-review failed for ban_id=%s", ban_id)
            claimed = False
        if not claimed:
            log.warning(
                "Appeal submit lost the review race for ban_id=%s; "
                "discarding duplicate review_msg_id=%d",
                ban_id,
                review_msg_id,
            )
            try:
                await ctx.bot.delete_message(
                    chat_id=flow_pkg.cfg.main_group, message_id=review_msg_id
                )
            except Exception as exc:
                log.debug(
                    "Appeal orphan-card delete failed for ban_id=%s: %s",
                    ban_id,
                    exc,
                )
            if appeals_review_id:
                try:
                    await ctx.bot.delete_message(
                        chat_id=appeal_chat, message_id=appeals_review_id
                    )
                except Exception as exc:
                    log.debug(
                        "Appeal orphan APPEALS-copy delete failed for ban_id=%s: %s",
                        ban_id,
                        exc,
                    )
            await safe_reply(
                msg,
                t(
                    "appeals.submit.pending_review",
                    locale,
                    hours=_STALE_REVIEW_HOURS,
                    plain=True,
                ),
                log_label="Appeal race-loser",
                parse_mode=None,
            )
            _clear_appeal_state(ctx.user_data)
            return ConversationHandler.END
    if appeal_log_sent_id and ban_id:
        try:
            await db.bans_db.set_appeal_log_msg(
                ban_id, appeal_log_sent_id, appeal_link=appeal_link
            )
        except Exception:
            log.exception("Appeal DB write failed for ban_id=%s", ban_id)

    # * Edit instruction message + cache user in parallel
    instr_mid = ctx.user_data.get("appeal_instruction_msg_id")
    edit_coro = (
        ctx.bot.edit_message_text(
            t("appeals.submit.submitted", locale, plain=True),
            chat_id=update.effective_chat.id if update.effective_chat else None,
            message_id=instr_mid,
            # * Strip the Cancel keyboard: the conversation ends here and
            # * a live button would spin forever with no handler behind it.
            reply_markup=None,
        )
        if instr_mid and update.effective_chat
        else None
    )
    upsert_coro = db.users_cache.upsert_user(
        uid, user.username, user.first_name, user.last_name
    )

    if edit_coro is not None:
        edit_r, upsert_r = await asyncio.gather(
            edit_coro, upsert_coro, return_exceptions=True
        )
        throw_if_cancelled((edit_r, upsert_r))
        if isinstance(edit_r, BaseException):
            log.debug("Appeal submitted-edit failed for ban_id=%s: %s", ban_id, edit_r)
        if isinstance(upsert_r, BaseException):
            log.warning(
                "Appeal user-cache upsert failed for user=%d: %s",
                uid,
                upsert_r,
            )
    else:
        try:
            await upsert_coro
        except Exception as exc:
            log.warning("Appeal user-cache upsert failed for user=%d: %s", uid, exc)

    # * If the review post (``rv``) failed, staff has no actionable
    # * review card and no pending-review marker was claimed, so the
    # * normal review workflow can never pick this appeal up. Tell the
    # * user delivery failed instead of "submitted", even when the
    # * log-channel post landed (a retry may duplicate that log line,
    # * which is harmless next to a lost appeal).
    if review_msg_id is None:
        log.error(
            "submit_appeal: review post failed "
            "for user=%d ban=%s (log posted=%s); no review card exists",
            uid,
            ban_id,
            appeal_log_sent_id is not None,
        )
        # * Drop the APPEALS copy so a retry never leaves an actionable
        # * card without a claimed review slot.
        if appeals_review_id:
            try:
                await ctx.bot.delete_message(
                    chat_id=appeal_chat, message_id=appeals_review_id
                )
            except Exception as exc:
                log.debug(
                    "submit_appeal orphan APPEALS-copy delete failed for ban_id=%s: %s",
                    ban_id,
                    exc,
                )
        if instr_mid and update.effective_chat:
            try:
                await ctx.bot.edit_message_text(
                    t("appeals.submit.delivery_failed", locale, plain=True),
                    chat_id=update.effective_chat.id,
                    message_id=instr_mid,
                )
            except Exception as exc:
                log.debug("submit_appeal delivery-failed reply failed: %s", exc)
        # * Stay in WAITING_APPEAL with user_data intact so the user can
        # * retry by sending another #appeal message without reopening
        # * the deep link. Returning END here would end the conversation
        # * while keeping stale keys, leaving no in-place retry path.
        return WAITING_APPEAL

    # * Clear appeal keys so user_data is clean after successful submission.
    _clear_appeal_state(ctx.user_data)

    return ConversationHandler.END
