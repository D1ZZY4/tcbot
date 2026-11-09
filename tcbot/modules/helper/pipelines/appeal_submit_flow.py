# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Appeal submission: DM deep-link entry, validation gates, and review posting."""

from __future__ import annotations

import asyncio
import contextlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from telegram import Message, Update
from telegram.ext import (
    CallbackQueryHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from tcbot import cfg, tme_handle_from_url
from tcbot import database as db
from tcbot.modules.helper import messages
from tcbot.modules.helper.keyboards import appeal_cancel_kb, appeal_review_kb
from tcbot.modules.helper.locale import locale_for_update
from tcbot.modules.helper.messages import safe_reply
from tcbot.modules.helper.parse_link import message_link
from tcbot.modules.helper.pipelines.appeal_review_flow import AppealReviewMixin
from tcbot.utils.dispatch import throw_if_cancelled
from tcbot.utils.formatter import pre
from tcbot.utils.i18n import t
from tcbot.utils.logger import get_logger
from tcbot.utils.prefixes import ALL_PREFIXES_CMD_FILTER
from tcbot.utils.time_and_date import to_utc, utc_now

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from telegram import User
    from telegram.ext.filters import BaseFilter

log = get_logger(__name__)

# ──────────────────────── Submission gates ──────────────────────── #


WAITING_APPEAL = 0
_MAX_APPEAL_LEN: int = 2000
_STALE_REVIEW_HOURS: int = 72
_STALE_REVIEW_WINDOW = timedelta(hours=_STALE_REVIEW_HOURS)
_REJECTION_COOLDOWN_HOURS: int = 24
_REJECTION_COOLDOWN = timedelta(hours=_REJECTION_COOLDOWN_HOURS)
_SECONDS_PER_HOUR: int = 3600
_ID_RE = re.compile(r"^/start\s+appeal_([a-z0-9]{10})$")
_APPEAL_STATE_KEYS: tuple[str, ...] = (
    "appeal_ban_id",
    "appeal_log_msg_id",
    "appeal_instruction_msg_id",
)


def starts_with_appeal_tag(text: str) -> bool:
    """Return True when text starts with #appeal (case-insensitive)."""
    return text.strip().lower().startswith("#appeal")


def text_references_log_message(text: str, msg_id: int) -> bool:
    """Return True when text contains msg_id as a standalone token."""
    return bool(re.search(rf"\b{msg_id}\b", text))


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
    """Return remaining whole hours inside the rejection cooldown, else None."""
    if rejected_at is None:
        return None
    elapsed = utc_now() - to_utc(rejected_at)
    if elapsed < timedelta(0):
        elapsed = timedelta(0)
    if elapsed >= _REJECTION_COOLDOWN:
        return None
    total = int((_REJECTION_COOLDOWN - elapsed).total_seconds())
    return (total + _SECONDS_PER_HOUR - 1) // _SECONDS_PER_HOUR


def instruction_text(
    *, community_name: str, log_channel: str, locale: str | None
) -> str:
    """Render the multi-line MarkdownV2 instruction prompt."""
    log_handle = log_channel.lstrip("@")
    example = pre(
        t(
            "appeals.instruction.example_body",
            locale,
            logs=log_handle,
            plain=True,
        )
    )
    return (
        f"{t('appeals.instruction.title', locale, community=community_name)}\n\n"
        f"{t('appeals.instruction.intro', locale)}\n"
        f"{t('appeals.instruction.log_item', locale)}\n"
        f"{t('appeals.instruction.clarify_item', locale)}\n"
        f"{t('appeals.instruction.agree_item', locale)}\n\n"
        f"{t('appeals.instruction.example_label', locale)}\n"
        f"{example}\n\n"
        f"{t('appeals.instruction.channel', locale, handle=log_channel)}"
    )


# ──────────────────────── Main-group entry ──────────────────────── #


async def handle_group_appeal(
    update: Update,
    ctx: ContextTypes.DEFAULT_TYPE,
    on_message: Callable[..., Awaitable[int]],
) -> None:
    """Handle #appeal in the main group through the DM submit path."""
    msg = update.effective_message
    user = update.effective_user
    chat = update.effective_chat
    if msg is None or user is None or msg.text is None or chat is None:
        return
    if chat.id != cfg.main_group or not chat.id:
        return
    text = msg.text.strip()
    if not starts_with_appeal_tag(text):
        return
    locale = await locale_for_update(update)
    try:
        ban = await db.bans_db.get_active_ban(user.id)
    except Exception:
        log.exception("Appeal group lookup failed for user=%d", user.id)
        ban = None
    bid = str(ban.get("ban_id", "")) if ban else ""
    if not ban or not bid:
        await safe_reply(
            msg,
            t("appeals.submit.invalid_link", locale, plain=True),
            log_label="Appeal group no-ban",
            parse_mode=None,
        )
        return
    mentioned = re.search(r"\b([a-z0-9]{10})\b", text)
    if mentioned and mentioned.group(1) != bid:
        await safe_reply(
            msg,
            t("appeals.submit.invalid_link", locale, plain=True),
            log_label="Appeal group id-mismatch",
            parse_mode=None,
        )
        return
    if ctx.user_data is None:
        return
    ctx.user_data["appeal_ban_id"] = bid
    ctx.user_data["appeal_log_msg_id"] = ban.get("log_message_id", 0)
    result = await on_message(update, ctx)
    if result != WAITING_APPEAL:
        _clear_appeal_state(ctx.user_data)


# ─────────────────────────── Submit step ────────────────────────── #


class SubmitMessageMixin:
    """Text-message submit step: gates, review posting, and delivery retry."""

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
        if fresh_ban.get("review_message_id"):
            if _is_stale_review(fresh_ban.get("review_timestamp")):
                try:
                    await db.bans_db.clear_review(ban_id)
                except Exception:
                    _who = update.effective_user
                    log.exception(
                        "Appeal _on_message: failed to clear stale review for "
                        "ban_id=%s user=%d",
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


# ───────────────────────── Review posting ───────────────────────── #


async def post_appeal(
    update: Update,
    ctx: ContextTypes.DEFAULT_TYPE,
    msg: Message,
    user: User,
    uid: int,
    ban_id: str,
    locale: str | None,
) -> int:
    """Forward a validated appeal and post its dual review cards."""
    if ctx.user_data is None:
        log.error("ctx.user_data is None in appeal posting")
        return ConversationHandler.END
    appeal_chat, appeal_thread = cfg.appeals
    appeal_msg_id: int | None = None
    try:
        fwd = await msg.forward(appeal_chat, message_thread_id=appeal_thread)
        appeal_msg_id = fwd.message_id
    except Exception:
        log.exception("Appeal forward failed")
    appeal_link = (
        message_link(appeal_chat, appeal_msg_id, appeal_thread) if appeal_msg_id else ""
    )
    review_text = messages.appeal_received_log(
        uid, user.first_name, ban_id, appeal_link
    )
    lc, lt = cfg.logs
    rv, rv_appeals, sent_log = await asyncio.gather(
        ctx.bot.send_message(
            cfg.main_group,
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
            messages.appeal_submitted_log(uid, user.first_name, ban_id, appeal_link),
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
    claimed = False
    if review_msg_id:
        # * Atomic claim: concurrent submits can never both win this slot.
        try:
            claimed = await db.bans_db.set_review_if_absent(ban_id, review_msg_id)
        except Exception:
            log.exception("Appeal claim-review failed for ban_id=%s", ban_id)
            claimed = False
        if not claimed:
            log.warning(
                "Appeal submit lost the review race for ban_id=%s; discarding %d",
                ban_id,
                review_msg_id,
            )
            try:
                await ctx.bot.delete_message(
                    chat_id=cfg.main_group, message_id=review_msg_id
                )
            except Exception as exc:
                log.debug("Appeal orphan-card delete failed for %s: %s", ban_id, exc)
            if appeals_review_id:
                try:
                    await ctx.bot.delete_message(
                        chat_id=appeal_chat, message_id=appeals_review_id
                    )
                except Exception as exc:
                    log.debug(
                        "Appeal orphan APPEALS delete failed for %s: %s", ban_id, exc
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
    instr_mid = ctx.user_data.get("appeal_instruction_msg_id")
    edit_coro = (
        ctx.bot.edit_message_text(
            t("appeals.submit.submitted", locale, plain=True),
            chat_id=update.effective_chat.id if update.effective_chat else None,
            message_id=instr_mid,
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
            log.debug("Appeal submitted-edit failed for %s: %s", ban_id, edit_r)
        if isinstance(upsert_r, BaseException):
            log.warning("Appeal user-cache upsert failed for %d: %s", uid, upsert_r)
    else:
        try:
            await upsert_coro
        except Exception as exc:
            log.warning("Appeal user-cache upsert failed for %d: %s", uid, exc)
    if review_msg_id is None:
        log.error(
            "submit_appeal: review post failed for user=%d ban=%s",
            uid,
            ban_id,
        )
        if appeals_review_id:
            try:
                await ctx.bot.delete_message(
                    chat_id=appeal_chat, message_id=appeals_review_id
                )
            except Exception as exc:
                log.debug(
                    "submit_appeal orphan APPEALS delete failed for %s: %s", ban_id, exc
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
        return WAITING_APPEAL
    _clear_appeal_state(ctx.user_data)
    return ConversationHandler.END


# ───────────────────────── Submission flow ──────────────────────── #


class AppealSubmitMixin(SubmitMessageMixin):
    """User-side appeal submission: entry, gates, posting, and cancel paths."""

    community_name: str
    log_channel: str
    cancel_label: str
    cancel_callback: str

    def instruction_text(self, locale: str | None = None) -> str:
        """Multi-line MarkdownV2 instruction prompt."""
        return instruction_text(
            community_name=self.community_name,
            log_channel=self.log_channel,
            locale=locale,
        )

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
                try:
                    await db.bans_db.clear_review(ban_id)
                except Exception:
                    log.exception(
                        "Appeal _start: failed to clear stale review for ban_id=%s user=%d",
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
                    "Appeal _start: stale review cleared for ban_id=%s user=%d",
                    ban_id,
                    uid,
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
            _clear_appeal_state(ctx.user_data)
            return ConversationHandler.END
        return WAITING_APPEAL

    async def _on_entry(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
        """Entry-point handler; parses the /start appeal deep link."""
        msg = update.effective_message
        if msg is None or msg.text is None:
            return ConversationHandler.END
        m = _ID_RE.match(msg.text.strip())
        if not m:
            return ConversationHandler.END
        return await self._start(update, ctx, m.group(1))

    async def on_group_appeal(
        self, update: Update, ctx: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle #appeal in the main group via the DM submit path."""
        await handle_group_appeal(update, ctx, self._on_message)

    async def _on_cancel(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
        """Cancel button handler; clears state and ends the conversation."""
        q = update.callback_query
        if q is None:
            return ConversationHandler.END
        live_mid = (ctx.user_data or {}).get("appeal_instruction_msg_id")
        tap_mid = q.message.message_id if q.message is not None else None
        if live_mid is not None and tap_mid is not None and tap_mid != live_mid:
            try:
                await q.answer()
            except Exception as exc:
                log.debug("appeal stale-cancel answer failed: %s", exc)
            return ConversationHandler.END
        _clear_appeal_state(ctx.user_data)
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
        """Fallback handler; fires on any unrecognised command."""
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
            )
        return ConversationHandler.END

    async def _on_unexpected(
        self, update: Update, ctx: ContextTypes.DEFAULT_TYPE
    ) -> int:
        """Non-text message handler; nudge back to text."""
        msg = update.effective_message
        if msg is not None:
            await safe_reply(
                msg,
                t(
                    "appeals.submit.unexpected",
                    await locale_for_update(update),
                    plain=True,
                ),
                log_label="Appeal unexpected-type",
            )
        return WAITING_APPEAL

    def build_handler(self, entry_filter: BaseFilter) -> ConversationHandler:
        """Assemble and return the appeal ConversationHandler."""
        return build_handler(
            entry_filter=entry_filter,
            on_entry=self._on_entry,
            on_cancel=self._on_cancel,
            on_message=self._on_message,
            on_unexpected=self._on_unexpected,
            on_end=self._end,
            cancel_callback=self.cancel_callback,
        )


# ─────────────────── ConversationHandler factory ────────────────── #


def build_handler(
    *,
    entry_filter: BaseFilter,
    on_entry: Callable,
    on_cancel: Callable,
    on_message: Callable,
    on_unexpected: Callable,
    on_end: Callable,
    cancel_callback: str,
) -> ConversationHandler:
    """Assemble the appeal ConversationHandler from bound step methods."""
    return ConversationHandler(
        entry_points=[MessageHandler(entry_filter, on_entry)],
        states={
            WAITING_APPEAL: [
                CallbackQueryHandler(
                    on_cancel,
                    pattern=rf"^{re.escape(cancel_callback)}$",
                ),
                MessageHandler(
                    filters.ChatType.PRIVATE & filters.TEXT & ~ALL_PREFIXES_CMD_FILTER,
                    on_message,
                ),
                MessageHandler(
                    filters.ChatType.PRIVATE & ~filters.TEXT & ~ALL_PREFIXES_CMD_FILTER,
                    on_unexpected,
                ),
            ],
        },
        fallbacks=[
            MessageHandler(entry_filter, on_entry),
            MessageHandler(ALL_PREFIXES_CMD_FILTER, on_end),
        ],
        per_chat=True,
        per_user=True,
        per_message=False,
    )


@dataclass(frozen=True)
class BuildAppeal(AppealSubmitMixin, AppealReviewMixin):
    """Configurable appeal ConversationHandler builder."""

    community_name: str
    log_channel: str
    cancel_label: str = field(default="Cancel", kw_only=True)
    cancel_callback: str = field(default="cancel_appeal", kw_only=True)


appeal = BuildAppeal(cfg.community_name, tme_handle_from_url(cfg.community_logs_url))
