# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Appeal submission: DM deep-link entry, validation gates, and review posting."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from telegram.ext import (
    CallbackQueryHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from tcbot import cfg
from tcbot import database as db
from tcbot.modules.helper import parse_logmsg
from tcbot.modules.helper.keyboards import appeal_cancel_kb, appeal_review_kb
from tcbot.modules.helper.locale import locale_for_update
from tcbot.modules.helper.parse_editmsg import safe_reply
from tcbot.modules.helper.parse_link import message_link
from tcbot.utils.formatter import pre
from tcbot.utils.i18n import t
from tcbot.utils.prefixes import ALL_PREFIXES_CMD_FILTER
from tcbot.utils.time_and_date import to_utc, utc_now

if TYPE_CHECKING:
    from telegram import Update
    from telegram.ext.filters import BaseFilter

log = logging.getLogger(__name__)

WAITING_APPEAL = 0

# * Maximum character length for an appeal message.
_MAX_APPEAL_LEN: int = 2000
_STALE_REVIEW_HOURS: int = 72
_STALE_REVIEW_WINDOW = timedelta(hours=_STALE_REVIEW_HOURS)
_REJECTION_COOLDOWN_HOURS: int = 24
_REJECTION_COOLDOWN = timedelta(hours=_REJECTION_COOLDOWN_HOURS)
_SECONDS_PER_HOUR: int = 3600

_ID_RE = re.compile(r"^/start\s+appeal_([a-z0-9]{10})$")

# * Appeal runtime prose lives in appeals.toml [submit]/[instruction];
# * only numeric tunables stay in code.


# ─────────────────────── Appeal pure helpers ────────────────────── #


def starts_with_appeal_tag(text: str) -> bool:
    """Return True when text (stripped) starts with #appeal (case-insensitive)."""
    return text.strip().lower().startswith("#appeal")


def text_references_log_message(text: str, msg_id: int) -> bool:
    """Return True when text contains msg_id as a standalone integer token."""
    return bool(re.search(rf"\b{msg_id}\b", text))


# * Conversation keys shared by every appeal exit path. One tuple so a
# * future key cannot be cleared in _start and leak in _on_message.
_APPEAL_STATE_KEYS: tuple[str, ...] = (
    "appeal_ban_id",
    "appeal_log_msg_id",
    "appeal_instruction_msg_id",
)


def _clear_appeal_state(user_data: dict[str, object] | None) -> None:
    """Remove appeal conversation keys so retries start clean."""
    if not user_data:
        return
    for key in _APPEAL_STATE_KEYS:
        user_data.pop(key, None)


def _is_stale_review(review_ts: datetime | None) -> bool:
    """Return True when a stored review no longer blocks a new appeal."""
    return review_ts is None or (to_utc(review_ts) < utc_now() - _STALE_REVIEW_WINDOW)


def _cooldown_remaining_h(rejected_at: datetime | None) -> int | None:
    """Return remaining whole hours plus one inside the rejection cooldown, else None."""
    if rejected_at is None:
        return None
    elapsed = utc_now() - to_utc(rejected_at)
    if elapsed < timedelta(0):
        elapsed = timedelta(0)
    if elapsed >= _REJECTION_COOLDOWN:
        return None
    return int((_REJECTION_COOLDOWN - elapsed).total_seconds() / _SECONDS_PER_HOUR) + 1


# ────────────────────── Submission mixin ───────────────────── #


class AppealSubmitMixin:
    """User-side appeal submission: entry, gates, posting, and cancel paths.

    Combined with ``AppealReviewMixin`` in ``appeal_flow.BuildAppeal``; the
    attribute declarations below are provided by that concrete subclass.
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

        locale = await locale_for_update(update)
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

        _clear_appeal_state(ctx.user_data)

        # * Answer before the visible edit so the client spinner clears
        # * first; mirrors ban_flow.on_cancel_proof sequential ordering.
        try:
            await q.answer()
        except Exception as exc:
            log.debug("appeal cancel answer failed: %s", exc)
        try:
            locale = await locale_for_update(update)
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
                    await locale_for_update(update),
                    plain=True,
                ),
                log_label="Appeal _end",
                parse_mode=None,
            )
        return ConversationHandler.END

    async def _on_message(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
        """Text message handler; validates and submits a #appeal message."""
        msg = update.effective_message
        if msg is None or msg.text is None:
            return WAITING_APPEAL

        text = msg.text.strip()

        locale = await locale_for_update(update)
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

        uid = user.id

        appeal_chat, appeal_thread = cfg.appeals
        appeal_msg_id: int | None = None
        try:
            fwd = await msg.forward(appeal_chat, message_thread_id=appeal_thread)
            appeal_msg_id = fwd.message_id
        except Exception:
            log.exception("Appeal forward failed")

        appeal_link = (
            message_link(appeal_chat, appeal_msg_id, appeal_thread)
            if appeal_msg_id
            else ""
        )
        review_text = parse_logmsg.appeal_received_log(
            uid, user.first_name, ban_id, appeal_link
        )
        lc, lt = cfg.logs

        # * Send review post + log message in parallel
        rv, sent_log = await asyncio.gather(
            ctx.bot.send_message(
                cfg.main_group,
                review_text,
                parse_mode="MarkdownV2",
                message_thread_id=cfg.appeal_discussion_topic or None,
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

        review_msg_id: int | None = (
            rv.message_id if not isinstance(rv, BaseException) else None
        )
        if isinstance(rv, BaseException):
            log.error("Appeal review post failed: %s", rv)

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
                        chat_id=cfg.main_group, message_id=review_msg_id
                    )
                except Exception as exc:
                    log.debug(
                        "Appeal orphan-card delete failed for ban_id=%s: %s",
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
            if isinstance(edit_r, BaseException):
                log.debug(
                    "Appeal submitted-edit failed for ban_id=%s: %s", ban_id, edit_r
                )
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

        # * If BOTH the review post (``rv``) and the log post (``sent_log``)
        # * failed, staff will never see the appeal and the user is left
        # * waiting for a reply that will never come. Edit the instruction
        # * message to a clear "we could not deliver your appeal" reply,
        # * otherwise the user believes the appeal was received and may not
        # * re-submit for a long time.
        if review_msg_id is None and appeal_log_sent_id is None:
            log.error(
                "submit_appeal: BOTH review post and appeal log post failed "
                "for user=%d ban=%s; the appeal was not delivered to staff",
                uid,
                ban_id,
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
                ],
            },
            fallbacks=[
                MessageHandler(ALL_PREFIXES_CMD_FILTER, self._end),
            ],
            per_chat=True,
            per_user=True,
            per_message=False,
        )
