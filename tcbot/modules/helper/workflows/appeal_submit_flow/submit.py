# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Message-submit step of the appeal flow: validation before posting."""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING

from telegram.ext import ConversationHandler

from tcbot import database as db
from tcbot.modules.helper.parse_editmsg import safe_reply
from tcbot.modules.helper.workflows import appeal_submit_flow as flow_pkg
from tcbot.modules.helper.workflows.appeal_submit_flow.gates import (
    _MAX_APPEAL_LEN,
    _REJECTION_COOLDOWN_HOURS,
    _STALE_REVIEW_HOURS,
    WAITING_APPEAL,
    _clear_appeal_state,
    _cooldown_remaining_h,
    _is_stale_review,
    starts_with_appeal_tag,
    text_references_log_message,
)
from tcbot.modules.helper.workflows.appeal_submit_flow.posting import post_appeal
from tcbot.utils.i18n import t
from tcbot.utils.logger import get_logger

if TYPE_CHECKING:
    from telegram import Update
    from telegram.ext import ContextTypes

log = get_logger(__name__)


class SubmitMessageMixin:
    """Text-message submit step: gates, review posting, and delivery retry.

    Combined into ``AppealSubmitMixin``; ``cfg`` and locale lookups resolve
    through the package namespace (``flow_pkg``) so package-level
    monkeypatching keeps working as it did for the flat module.
    """

    async def _on_message(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
        """Text message handler; validates and submits a #appeal message."""
        msg = update.effective_message
        if msg is None or msg.text is None:
            return WAITING_APPEAL
        text = msg.text.strip()

        locale = await flow_pkg.locale_for_update(update)
        if not starts_with_appeal_tag(text):
            await safe_reply(
                msg,
                t("appeals.submit.unexpected", locale, plain=True),
                log_label="Appeal unexpected-text",
                parse_mode=None,
            )
            return WAITING_APPEAL

        if len(text) > _MAX_APPEAL_LEN:
            await safe_reply(
                msg,
                t(
                    "appeals.submit.too_long",
                    locale,
                    max=_MAX_APPEAL_LEN,
                    plain=True,
                ),
                log_label="Appeal too-long",
                parse_mode=None,
            )
            return WAITING_APPEAL

        if ctx.user_data is None:
            log.error("ctx.user_data is None in appeal_flow _on_message")
            return ConversationHandler.END

        ban_id = ctx.user_data.get("appeal_ban_id")
        log_msg_id = ctx.user_data.get("appeal_log_msg_id", 0)

        if not ban_id:
            await safe_reply(
                msg,
                t("appeals.submit.session_expired", locale, plain=True),
                log_label="Appeal _on_message session-expired",
                parse_mode=None,
            )
            return ConversationHandler.END

        # * Revalidate against a fresh ban record: the ban may have been
        # * deactivated, or the cached log_message_id may be a transient 0
        # * from a ban update. Submitting against stale state would orphan
        # * a review card on an inactive ban.
        try:
            fresh_ban = await db.bans_db.get_ban(ban_id)
        except Exception:
            log.exception("Appeal _on_message get_ban failed for %s", ban_id)
            fresh_ban = None
        if not fresh_ban or not fresh_ban.get("is_active"):
            await safe_reply(
                msg,
                t("appeals.submit.session_expired", locale, plain=True),
                log_label="Appeal _on_message expired-ban",
                parse_mode=None,
            )
            _clear_appeal_state(ctx.user_data)
            return ConversationHandler.END

        # * Re-check the pending-review and rejection-cooldown gates from
        # * _start: the ban may have gained a review (concurrent submit from
        # * another session) or a rejection while this conversation waited
        # * for the user to type. Submitting anyway would orphan a review
        # * card or bypass the cooldown.
        if fresh_ban.get("review_message_id"):
            if _is_stale_review(fresh_ban.get("review_timestamp")):
                try:
                    await db.bans_db.clear_review(ban_id)
                except Exception:
                    _who = update.effective_user
                    log.exception(
                        "Appeal _on_message: failed to clear stale review for "
                        "ban_id=%s user=%d; blocking submit to avoid corrupt state",
                        ban_id,
                        _who.id if _who is not None else 0,
                    )
                    with contextlib.suppress(Exception):
                        await msg.reply_text(
                            t(
                                "appeals.submit.pending_review",
                                locale,
                                hours=_STALE_REVIEW_HOURS,
                                plain=True,
                            )
                        )
                    _clear_appeal_state(ctx.user_data)
                    return ConversationHandler.END
            else:
                await safe_reply(
                    msg,
                    t(
                        "appeals.submit.pending_review",
                        locale,
                        hours=_STALE_REVIEW_HOURS,
                        plain=True,
                    ),
                    log_label="Appeal _on_message pending-review",
                    parse_mode=None,
                )
                _clear_appeal_state(ctx.user_data)
                return ConversationHandler.END

        remaining_h = _cooldown_remaining_h(fresh_ban.get("rejected_at"))
        if remaining_h is not None:
            await safe_reply(
                msg,
                t(
                    "appeals.submit.cooldown",
                    locale,
                    hours=_REJECTION_COOLDOWN_HOURS,
                    remaining=remaining_h,
                    plain=True,
                ),
                log_label="Appeal _on_message cooldown",
                parse_mode=None,
            )
            _clear_appeal_state(ctx.user_data)
            return ConversationHandler.END

        if not log_msg_id:
            log_msg_id = fresh_ban.get("log_message_id", 0)

        if log_msg_id and not text_references_log_message(text, log_msg_id):
            await safe_reply(
                msg,
                t("appeals.submit.invalid_log", locale, plain=True),
                log_label="Appeal _on_message invalid-log",
                parse_mode=None,
            )
            return WAITING_APPEAL

        user = update.effective_user
        if user is None:
            _clear_appeal_state(ctx.user_data)
            return ConversationHandler.END

        return await post_appeal(update, ctx, msg, user, user.id, str(ban_id), locale)
