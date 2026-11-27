# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Appeal posting: forward the appeal and place its two review cards."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from tcbot import cfg
from tcbot import database as db
from tcbot.modules.helper import messages
from tcbot.modules.helper.buttons import appeal_review_btn
from tcbot.modules.helper.context import Ctx, chat_id_of, display_name
from tcbot.modules.helper.handlers import ConversationHandler
from tcbot.modules.helper.messages import (
    forward_rich,
    message_link,
    reply_rich,
    safe_edit_message,
    send_log,
    send_text,
)
from tcbot.modules.helper.pipelines.appeal_post_edit import (
    edit_instruction,
    report_delivery_failure,
)
from tcbot.modules.helper.scope import flow_scope
from tcbot.utils.dispatch import throw_if_cancelled
from tcbot.utils.i18n import t
from tcbot.utils.logger import get_logger

if TYPE_CHECKING:
    from pyrogram.types import Message, User

log = get_logger(__name__)

WAITING_APPEAL: int = 0
_STALE_REVIEW_HOURS: int = 72
_APPEAL_STATE_KEYS: tuple[str, ...] = (
    "appeal_ban_id",
    "appeal_log_msg_id",
    "appeal_instruction_msg_id",
)


def clear_appeal_state(scope: dict[str, object]) -> None:
    """Remove appeal conversation keys so retries start clean."""
    for key in _APPEAL_STATE_KEYS:
        scope.pop(key, None)


async def post_appeal(
    ctx: Ctx,
    msg: Message,
    user: User,
    uid: int,
    ban_id: str,
    locale: str | None,
    appeal_text: str,
) -> int:
    """Forward a validated appeal and post its dual review cards."""
    if ctx.user_data is None:
        log.error("ctx.user_data is None in appeal posting")
        return ConversationHandler.END
    scope = flow_scope(ctx)
    appeal_chat, appeal_thread = cfg.appeals
    appeal_msg_id: int | None = None
    try:
        fwd = await forward_rich(msg, appeal_chat, message_thread_id=appeal_thread)
        # * Kurigram returns a list for an album forward; a single appeal
        # * message is the only shape that yields a usable link id.
        if fwd is not None and not isinstance(fwd, list):
            appeal_msg_id = fwd.id
    except Exception:
        log.exception("Appeal forward failed")
    appeal_link = (
        message_link(appeal_chat, appeal_msg_id, appeal_thread) if appeal_msg_id else ""
    )
    linked_rules: list[str] = []
    try:
        banned = await db.bans_db.get_ban(ban_id)
        if banned is not None:
            linked_rules = list(banned.get("rules") or [])
    except Exception as exc:
        log.debug("Appeal rule lookup failed for %s: %s", ban_id, exc)
    review_text = messages.appeal_received_log(
        uid,
        display_name(user),
        ban_id,
        appeal_link,
        linked_rules,
        appeal_excerpt=appeal_text if not appeal_link else "",
    )
    # * The review card id is the decision token, so the main card is posted
    # * first and its keyboard is attached once the id is known.
    try:
        rv = await send_text(ctx.bot, cfg.main_group, review_text)
    except Exception:
        log.exception("Appeal review post failed")
        rv = None
    review_msg_id: int | None = rv.id if rv is not None else None
    appeals_review_id: int | None = None
    appeal_log_sent_id: int | None = None
    if review_msg_id is not None:
        review_btn = appeal_review_btn(ban_id, review_msg_id, locale)
        rv_appeals, sent_log, markup = await asyncio.gather(
            send_text(
                ctx.bot,
                appeal_chat,
                review_text,
                message_thread_id=appeal_thread,
                reply_markup=review_btn,
            ),
            send_log(
                ctx.bot,
                messages.appeal_submitted_log(
                    uid, display_name(user), ban_id, appeal_link
                ),
            ),
            # * Attach the keyboard through the rich transport so the main
            # * card gets rich buttons like the APPEALS copy. A raw
            # * edit_message_reply_markup bypassed conversion entirely.
            safe_edit_message(
                ctx.bot,
                cfg.main_group,
                review_msg_id,
                review_text,
                reply_markup=review_btn,
            ),
            return_exceptions=True,
        )
        throw_if_cancelled((rv_appeals, sent_log, markup))
        if isinstance(sent_log, BaseException):
            log.error("Appeal log failed: %s", sent_log)
        else:
            appeal_log_sent_id = sent_log.id
        if isinstance(rv_appeals, BaseException):
            log.error("Appeal review copy to APPEALS failed: %s", rv_appeals)
        else:
            appeals_review_id = rv_appeals.id
        if markup is False or isinstance(markup, BaseException):
            # * A gone target returns False, not an exception. Without this
            # * branch the card id stays recorded and the appeal has no buttons.
            log.error("Appeal review keyboard attach failed: %s", markup)
            for chat_id, message_id in (
                (cfg.main_group, review_msg_id),
                (appeal_chat, appeals_review_id),
            ):
                if message_id is None:
                    continue
                try:
                    await ctx.bot.delete_messages(chat_id, message_id)
                except Exception as exc:
                    log.debug("Appeal undecidable-card delete failed: %s", exc)
            review_msg_id = None
            appeals_review_id = None
    claimed = False
    if review_msg_id:
        try:
            claimed = await db.bans_db.submit_appeal(
                ban_id, uid, appeal_text, review_msg_id
            )
        except Exception:
            log.exception("Appeal submit failed for ban_id=%s", ban_id)
            claimed = False
        if not claimed:
            log.warning(
                "Appeal submit lost the review race for ban_id=%s; discarding %d",
                ban_id,
                review_msg_id,
            )
            try:
                await ctx.bot.delete_messages(cfg.main_group, review_msg_id)
            except Exception as exc:
                log.debug("Appeal orphan-card delete failed for %s: %s", ban_id, exc)
            if appeals_review_id:
                try:
                    await ctx.bot.delete_messages(appeal_chat, appeals_review_id)
                except Exception as exc:
                    log.debug("Appeal orphan APPEALS delete failed: %s", exc)
            await reply_rich(
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
            clear_appeal_state(scope)
            return ConversationHandler.END
    if appeal_log_sent_id and ban_id:
        try:
            await db.bans_db.set_appeal_log_msg(
                ban_id, appeal_log_sent_id, appeal_link=appeal_link
            )
        except Exception:
            log.exception("Appeal DB write failed for ban_id=%s", ban_id)
    instr_mid = scope.get("appeal_instruction_msg_id")
    chat = ctx.effective_chat
    upsert_coro = db.users_cache.upsert_user(
        uid, user.username, display_name(user), user.last_name
    )
    if instr_mid and chat:
        edit_r, upsert_r = await asyncio.gather(
            edit_instruction(ctx.bot, chat_id_of(chat), instr_mid, locale),
            upsert_coro,
            return_exceptions=True,
        )
        throw_if_cancelled((edit_r, upsert_r))
        if isinstance(edit_r, BaseException):
            log.debug("Appeal submitted-edit failed for %s: %s", ban_id, edit_r)
        if isinstance(upsert_r, BaseException):
            log.warning("Appeal user-cache upsert failed for %d: %s", uid, upsert_r)
    else:
        try:
            await upsert_coro
        except Exception as exc:
            log.warning("Appeal user-cache upsert failed for %d: %s", uid, exc)
    if review_msg_id is None:
        log.error("submit_appeal: review post failed for user=%d ban=%s", uid, ban_id)
        await report_delivery_failure(
            ctx.bot,
            msg,
            locale,
            instruction_message_id=instr_mid or 0,
            instruction_chat_id=chat_id_of(chat) if chat else 0,
            orphan_review_id=appeals_review_id,
            appeal_chat=appeal_chat,
        )
        return WAITING_APPEAL
    clear_appeal_state(scope)
    return ConversationHandler.END
