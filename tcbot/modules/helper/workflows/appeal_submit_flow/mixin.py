# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""User-side appeal submission: entry, gates, posting, and cancel paths."""

from __future__ import annotations

import contextlib
import re
from typing import TYPE_CHECKING

from telegram.ext import (
    CallbackQueryHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from tcbot import database as db
from tcbot.modules.helper.keyboards import appeal_cancel_kb
from tcbot.modules.helper.parse_editmsg import safe_reply
from tcbot.modules.helper.workflows import appeal_submit_flow as flow_pkg
from tcbot.modules.helper.workflows.appeal_submit_flow.gates import (
    _ID_RE,
    _REJECTION_COOLDOWN_HOURS,
    _STALE_REVIEW_HOURS,
    WAITING_APPEAL,
    _clear_appeal_state,
    _cooldown_remaining_h,
    _is_stale_review,
)
from tcbot.modules.helper.workflows.appeal_submit_flow.submit import (
    SubmitMessageMixin,
)
from tcbot.utils.formatter import pre
from tcbot.utils.i18n import t
from tcbot.utils.logger import get_logger
from tcbot.utils.prefixes import ALL_PREFIXES_CMD_FILTER

if TYPE_CHECKING:
    from telegram import Update
    from telegram.ext.filters import BaseFilter

log = get_logger(__name__)


# ────────────────────── Submission mixin ───────────────────── #


class AppealSubmitMixin(SubmitMessageMixin):
    """User-side appeal submission: entry, gates, posting, and cancel paths.

    Combined with ``AppealReviewMixin`` in ``appeal_flow.BuildAppeal``; the
    attribute declarations below are provided by that concrete subclass.
    The ``_on_message`` step lives in ``SubmitMessageMixin``; ``cfg`` and
    locale lookups resolve through the package namespace (``flow_pkg``) so
    package-level monkeypatching keeps working as it did for the flat module.
    """

    community_name: str
    log_channel: str
    cancel_label: str
    cancel_callback: str

    # ── Text factory ─────────────────────────────────────────────────────────

    def instruction_text(self, locale: str | None = None) -> str:
        """Multi-line MarkdownV2 instruction prompt sent when the user opens an appeal."""
        log_handle = self.log_channel.lstrip("@")
        example = pre(
            t(
                "appeals.instruction.example_body",
                locale,
                logs=log_handle,
                plain=True,
            )
        )
        return (
            f"{t('appeals.instruction.title', locale, community=self.community_name)}\n\n"
            f"{t('appeals.instruction.intro', locale)}\n"
            f"{t('appeals.instruction.log_item', locale)}\n"
            f"{t('appeals.instruction.clarify_item', locale)}\n"
            f"{t('appeals.instruction.agree_item', locale)}\n\n"
            f"{t('appeals.instruction.example_label', locale)}\n"
            f"{example}\n\n"
            f"{t('appeals.instruction.channel', locale, handle=self.log_channel)}"
        )

    # ── ConversationHandler step methods ──────────────────────────────────

    async def _start(
        self, update: Update, ctx: ContextTypes.DEFAULT_TYPE, ban_id: str
    ) -> int:
        """Validate the deep-link and open the WAITING_APPEAL state."""
        msg = update.effective_message
        user = update.effective_user
        if msg is None or user is None:
            return ConversationHandler.END

        uid = user.id

        locale = await flow_pkg.locale_for_update(update)
        if update.effective_chat is None or update.effective_chat.type != "private":
            await safe_reply(
                msg,
                t("appeals.submit.not_private", locale, plain=True),
                log_label="Appeal not-private",
                parse_mode=None,
            )
            return ConversationHandler.END

        try:
            ban = await db.bans_db.get_ban(ban_id)
        except Exception:
            log.exception("Appeal _start: DB error fetching ban_id=%s", ban_id)
            with contextlib.suppress(Exception):
                await msg.reply_text(
                    t("appeals.submit.invalid_link", locale, plain=True)
                )
            return ConversationHandler.END
        if not ban or not ban.get("is_active"):
            await safe_reply(
                msg,
                t("appeals.submit.invalid_link", locale, plain=True),
                log_label=f"Appeal invalid-link for ban_id={ban_id}",
                parse_mode=None,
            )
            return ConversationHandler.END

        if ban.get("banned_user_id") != uid:
            await safe_reply(
                msg,
                t("appeals.submit.wrong_account", locale, plain=True),
                log_label=f"Appeal wrong-account for user {uid}",
                parse_mode=None,
            )
            return ConversationHandler.END

        if ban.get("review_message_id"):
            stale = _is_stale_review(ban.get("review_timestamp"))
            if stale:
                # * Review card is older than _STALE_REVIEW_HOURS (message may have been
                # * deleted from the discussion topic or staff never acted).  Clear the
                # * stale review state so the user can submit a fresh appeal.
                try:
                    await db.bans_db.clear_review(ban_id)
                except Exception:
                    log.exception(
                        "Appeal _start: failed to clear stale review for ban_id=%s"
                        " user=%d; blocking appeal to avoid corrupt state",
                        ban_id,
                        uid,
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
                    return ConversationHandler.END
                log.info(
                    "Appeal _start: stale review cleared for ban_id=%s user=%d"
                    " (review_ts=%s)",
                    ban_id,
                    uid,
                    ban.get("review_timestamp"),
                )
            else:
                await safe_reply(
                    msg,
                    t(
                        "appeals.submit.pending_review",
                        locale,
                        hours=_STALE_REVIEW_HOURS,
                        plain=True,
                    ),
                    log_label=f"Appeal pending-review for user {uid}",
                    parse_mode=None,
                )
                return ConversationHandler.END

        remaining_h = _cooldown_remaining_h(ban.get("rejected_at"))
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
                log_label=f"Appeal cooldown for user {uid}",
                parse_mode=None,
            )
            return ConversationHandler.END

        if ctx.user_data is None:
            log.error("ctx.user_data is None in appeal_flow _start")
            return ConversationHandler.END

        ctx.user_data["appeal_ban_id"] = ban_id
        ctx.user_data["appeal_log_msg_id"] = ban.get("log_message_id", 0)

        try:
            instr = await msg.reply_text(
                self.instruction_text(locale),
                parse_mode="MarkdownV2",
                reply_markup=appeal_cancel_kb(
                    t("button.cancel", locale, plain=True),
                    self.cancel_callback,
                    locale,
                ),
            )
            ctx.user_data["appeal_instruction_msg_id"] = instr.message_id
        except Exception as exc:
            log.debug("Appeal instruction send failed for user %d: %s", uid, exc)
            # * Clear keys set above so user_data does not contain stale appeal state
            # * if the user retries later or starts a different conversation.
            _clear_appeal_state(ctx.user_data)
            return ConversationHandler.END

        return WAITING_APPEAL

    async def _on_entry(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
        """Entry-point handler; parses the /start appeal_<id> deep link."""
        msg = update.effective_message
        if msg is None or msg.text is None:
            return ConversationHandler.END

        text = msg.text.strip()
        m = _ID_RE.match(text)
        if not m:
            return ConversationHandler.END
        return await self._start(update, ctx, m.group(1))

    async def _on_cancel(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
        """Cancel button handler; clears state and ends the conversation."""
        q = update.callback_query
        if q is None:
            return ConversationHandler.END

        # * Stale-prompt guard: a second appeal overwrites the stored
        # * instruction id, so a tap on the previous prompt must not wipe
        # * the live session (same pattern as the ban-flush session guard).
        live_mid = (ctx.user_data or {}).get("appeal_instruction_msg_id")
        tap_mid = q.message.message_id if q.message is not None else None
        if live_mid is not None and tap_mid is not None and tap_mid != live_mid:
            try:
                await q.answer()
            except Exception as exc:
                log.debug("appeal stale-cancel answer failed: %s", exc)
            return ConversationHandler.END

        _clear_appeal_state(ctx.user_data)

        # * Answer before the visible edit so the client spinner clears
        # * first; mirrors ban_flow.on_cancel_proof sequential ordering.
        try:
            await q.answer()
        except Exception as exc:
            log.debug("appeal cancel answer failed: %s", exc)
        try:
            locale = await flow_pkg.locale_for_update(update)
            await q.edit_message_text(t("appeals.submit.cancelled", locale, plain=True))
        except Exception:
            log.debug("appeal cancel edit failed (message may already be gone)")
        return ConversationHandler.END

    async def _end(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
        """Fallback handler; fires on any unrecognised command during the flow."""
        _clear_appeal_state(ctx.user_data)
        msg = update.effective_message
        if msg:
            await safe_reply(
                msg,
                t(
                    "appeals.submit.session_ended",
                    await flow_pkg.locale_for_update(update),
                    plain=True,
                ),
                log_label="Appeal _end",
                parse_mode=None,
            )
        return ConversationHandler.END

    async def _on_unexpected(
        self, update: Update, ctx: ContextTypes.DEFAULT_TYPE
    ) -> int:
        """Non-text message handler; nudge back to text instead of silence."""
        msg = update.effective_message
        if msg is not None:
            await safe_reply(
                msg,
                t(
                    "appeals.submit.unexpected",
                    await flow_pkg.locale_for_update(update),
                    plain=True,
                ),
                log_label="Appeal unexpected-type",
                parse_mode=None,
            )
        return WAITING_APPEAL

    # ── ConversationHandler factory ────────────────────────────────────────

    def build_handler(self, entry_filter: BaseFilter) -> ConversationHandler:
        """Assemble and return the appeal ConversationHandler.

        Note: ``conversation_timeout`` is intentionally absent.  PTB's timeout
        support requires the ``job-queue`` extra (APScheduler 3.x backend) which
        is already used by this project's persistent MongoDBJobStore setup.
        Stale sessions are detected via the 72-hour ``_STALE_REVIEW_WINDOW`` guard
        in ``_start`` and ended via the ``_end`` fallback (triggered on any command)
        or Cancel.
        """
        return ConversationHandler(
            entry_points=[MessageHandler(entry_filter, self._on_entry)],
            states={
                WAITING_APPEAL: [
                    CallbackQueryHandler(
                        self._on_cancel,
                        pattern=rf"^{re.escape(self.cancel_callback)}$",
                    ),
                    MessageHandler(
                        filters.ChatType.PRIVATE
                        & filters.TEXT
                        & ~ALL_PREFIXES_CMD_FILTER,
                        self._on_message,
                    ),
                    MessageHandler(
                        filters.ChatType.PRIVATE
                        & ~filters.TEXT
                        & ~ALL_PREFIXES_CMD_FILTER,
                        self._on_unexpected,
                    ),
                ],
            },
            fallbacks=[
                # * A fresh deep link restarts the flow instead of falling
                # * into the generic session-ended handler below.
                MessageHandler(entry_filter, self._on_entry),
                MessageHandler(ALL_PREFIXES_CMD_FILTER, self._end),
            ],
            per_chat=True,
            per_user=True,
            per_message=False,
        )
