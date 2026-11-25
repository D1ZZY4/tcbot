# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Appeal submission: DM deep-link entry, validation gates, and review posting."""

from __future__ import annotations

import contextlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from pyrogram import ContinuePropagation, filters

from tcbot import cfg
from tcbot import database as db
from tcbot.modules.helper.buttons import appeal_cancel_btn
from tcbot.modules.helper.context import Ctx
from tcbot.modules.helper.handlers import (
    CallbackQueryHandler,
    ConversationHandler,
    MessageHandler,
)
from tcbot.modules.helper.locale import locale_for_update
from tcbot.modules.helper.messages import (
    message_link,
    reply_rich,
    reply_rich_result,
    safe_edit_cb,
)
from tcbot.modules.helper.pipelines.appeal_post import clear_appeal_state, post_appeal
from tcbot.modules.helper.pipelines.appeal_review import AppealReviewMixin
from tcbot.modules.helper.rich.formats import heading
from tcbot.modules.helper.rich.link import display as display_community_link
from tcbot.modules.helper.rich.list import checklist
from tcbot.modules.helper.scope import flow_scope
from tcbot.utils.i18n import pre, t
from tcbot.utils.logger import get_logger
from tcbot.utils.prefixes import (
    ALL_PREFIXES_CMD_FILTER,
    build_conversation_escape_filter,
)
from tcbot.utils.time_and_date import to_utc, utc_now

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from pyrogram.filters import Filter as BaseFilter

log = get_logger(__name__)

# ──────────────────────── Submission gates ──────────────────────── #


WAITING_APPEAL = 0
_MAX_APPEAL_LEN: int = 2000
_STALE_REVIEW_HOURS: int = 72
_STALE_REVIEW_WINDOW = timedelta(hours=_STALE_REVIEW_HOURS)
_REJECTION_COOLDOWN_HOURS: int = 24
_REJECTION_COOLDOWN = timedelta(hours=_REJECTION_COOLDOWN_HOURS)
_SECONDS_PER_HOUR: int = 3600
# * The public reference of a decision accepts ten to thirty-two
# * lowercase alphanumerics, which is the range the column constraint
# * enforces. The link has to accept the whole range: a decision that
# * was imported from the legacy table carries a longer reference, and a
# * link that does not parse leaves the banned user without a way to
# * appeal.
REF_PATTERN: str = r"[a-z0-9]{10,32}"
_ID_RE = re.compile(rf"^/start\s+appeal_({REF_PATTERN})$")
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


def _example_log_link(log_channel: str) -> str:
    """Build a usable example message link from a log channel display value.

    The caller resolves the channel to a full URL or a numeric chat id. The
    example template needs one complete link, never a URL nested inside
    another. A numeric supergroup id uses the ``t.me/c/`` form.
    """
    raw = log_channel.strip()
    if raw.lstrip("-").isdigit():
        return message_link(int(raw), 1)
    if raw.startswith("https://t.me/"):
        tail = raw[len("https://t.me/") :].rstrip("/")
        first = tail.split("/", 1)[0]
        if "+" not in first and first != "c":
            return f"https://t.me/{first.lstrip('@')}/1"
        return raw
    return f"https://t.me/{raw.lstrip('@')}/1"


def instruction_text(
    *, community_name: str, log_channel: str, locale: str | None
) -> str:
    """Render the multi-line rich instruction prompt."""
    example = pre(
        t(
            "appeals.instruction.example_body",
            locale,
            log_link=_example_log_link(log_channel),
            plain=True,
        )
    )
    required = [
        t("appeals.instruction.log_item", locale).removeprefix("- "),
        t("appeals.instruction.clarify_item", locale).removeprefix("- "),
        t("appeals.instruction.agree_item", locale).removeprefix("- "),
    ]
    return (
        f"{heading(t('appeals.instruction.title', locale, community=community_name, plain=True), 2)}\n"
        f"{t('appeals.instruction.intro', locale)}\n"
        f"{checklist([(item, False) for item in required])}\n\n"
        f"{t('appeals.instruction.example_label', locale)}\n"
        f"{example}\n\n"
        f"{t('appeals.instruction.channel', locale, handle=log_channel)}"
    )


# ──────────────────────── Main-group entry ──────────────────────── #


async def handle_group_appeal(
    ctx: Ctx,
    on_message: Callable[..., Awaitable[int]],
) -> None:
    """Handle #appeal in the main group through the DM submit path."""
    msg = ctx.effective_message
    user = ctx.effective_user
    chat = ctx.effective_chat
    if msg is None or user is None or msg.text is None or chat is None:
        return
    if not cfg.is_primary_group(chat.id):
        return
    text = msg.text.strip()
    if not starts_with_appeal_tag(text):
        return
    locale = await locale_for_update(ctx)
    try:
        ban = await db.bans_db.get_active_ban(user.id)
    except Exception:
        log.exception("Appeal group lookup failed for user=%d", user.id)
        ban = None
    bid = str(ban.get("ban_id", "")) if ban else ""
    if not ban or not bid:
        await reply_rich(
            msg,
            t("appeals.submit.invalid_link", locale, plain=True),
            log_label="Appeal group no-ban",
            parse_mode=None,
        )
        return
    # * A free-form appeal can contain ordinary words that happen to match
    # * the public-reference shape. The message is always tied to the
    # * sender's own active ban, so only a labelled reference is meaningful;
    # * rejecting an unlabelled token would block legitimate appeals.
    if ctx.user_data is None:
        return
    scope = flow_scope(ctx)
    scope["appeal_ban_id"] = bid
    scope["appeal_log_msg_id"] = ban.get("log_message_id", 0)
    result = await on_message(ctx)
    if result != WAITING_APPEAL:
        clear_appeal_state(scope)


# ─────────────────────────── Submit step ────────────────────────── #


class SubmitMessageMixin:
    """Text-message submit step: gates, review posting, and delivery retry."""

    async def _on_message(self, ctx: Ctx) -> int:
        """Text message handler; validates and submits a #appeal message."""
        msg = ctx.effective_message
        if msg is None or msg.text is None:
            return WAITING_APPEAL
        text = msg.text.strip()
        locale = await locale_for_update(ctx)
        if not starts_with_appeal_tag(text):
            # * This state handler is flattened into group 0. With no active
            # * appeal it must let another module's text handler see the update.
            if not isinstance(ctx.user_data, dict) or not ctx.user_data.get(
                "appeal_ban_id"
            ):
                raise ContinuePropagation()
            await reply_rich(
                msg,
                t("appeals.submit.unexpected", locale, plain=True),
                log_label="Appeal unexpected-text",
                parse_mode=None,
            )
            return WAITING_APPEAL
        if len(text) > _MAX_APPEAL_LEN:
            await reply_rich(
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
        scope = flow_scope(ctx)
        ban_id = scope.get("appeal_ban_id")
        log_msg_id = scope.get("appeal_log_msg_id", 0)
        if not ban_id:
            await reply_rich(
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
            await reply_rich(
                msg,
                t("appeals.submit.session_expired", locale, plain=True),
                log_label="Appeal _on_message expired-ban",
                parse_mode=None,
            )
            clear_appeal_state(scope)
            return ConversationHandler.END
        user = ctx.effective_user
        if user is None:
            clear_appeal_state(scope)
            return ConversationHandler.END
        # * The decision has to belong to the sender. The deep link checks
        # * it once, but the conversation state is what carries the
        # * decision from the entry to this step, so the check is repeated
        # * where the appeal is actually filed.
        if fresh_ban.get("target_user_id") != user.id:
            await reply_rich(
                msg,
                t("appeals.submit.wrong_account", locale, plain=True),
                log_label="Appeal _on_message wrong-account",
                parse_mode=None,
            )
            clear_appeal_state(scope)
            return ConversationHandler.END
        if fresh_ban.get("review_message_id"):
            if _is_stale_review(fresh_ban.get("review_timestamp")):
                try:
                    # * The stale card is released together with the
                    # * appeal it belongs to, so the open appeal does
                    # * not keep the decision occupied.
                    await db.bans_db.release_stale_review(
                        ban_id, int(fresh_ban.get("review_message_id") or 0)
                    )
                except Exception:
                    _who = ctx.effective_user
                    log.exception(
                        "Appeal _on_message: failed to clear stale review for "
                        "ban_id=%s user=%d",
                        ban_id,
                        _who.id if _who is not None else 0,
                    )
                    with contextlib.suppress(Exception):
                        await reply_rich(
                            msg,
                            t(
                                "appeals.submit.pending_review",
                                locale,
                                hours=_STALE_REVIEW_HOURS,
                                plain=True,
                            ),
                            parse_mode=None,
                        )
                    clear_appeal_state(scope)
                    return ConversationHandler.END
            else:
                await reply_rich(
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
                clear_appeal_state(scope)
                return ConversationHandler.END
        remaining_h = _cooldown_remaining_h(fresh_ban.get("rejected_at"))
        if remaining_h is not None:
            await reply_rich(
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
            clear_appeal_state(scope)
            return ConversationHandler.END
        if not log_msg_id:
            log_msg_id = fresh_ban.get("log_message_id", 0)
        if log_msg_id and not text_references_log_message(text, log_msg_id):
            await reply_rich(
                msg,
                t("appeals.submit.invalid_log", locale, plain=True),
                log_label="Appeal _on_message invalid-log",
                parse_mode=None,
            )
            return WAITING_APPEAL
        return await post_appeal(ctx, msg, user, user.id, str(ban_id), locale, text)


# ───────────────────────── Submission steps ──────────────────────── #


class AppealSubmitMixin(SubmitMessageMixin):
    """User-side appeal submission: entry, gates, posting, and cancel paths."""

    community_name: str
    log_channel: int
    cancel_label: str
    cancel_callback: str

    def instruction_text(
        self, locale: str | None = None, log_display: str | None = None
    ) -> str:
        """Multi-line rich instruction prompt."""
        return instruction_text(
            community_name=self.community_name,
            log_channel=log_display or str(self.log_channel),
            locale=locale,
        )

    async def _start(self, ctx: Ctx, ban_id: str) -> int:
        """Validate the deep-link and open the WAITING_APPEAL state."""
        msg = ctx.effective_message
        user = ctx.effective_user
        if msg is None or user is None:
            return ConversationHandler.END
        uid = user.id
        locale = await locale_for_update(ctx)
        chat_type = (
            getattr(ctx.effective_chat, "type", None) if ctx.effective_chat else None
        )
        if chat_type is None or getattr(chat_type, "value", chat_type) != "private":
            await reply_rich(
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
                await reply_rich(
                    msg,
                    t("appeals.submit.invalid_link", locale, plain=True),
                    parse_mode=None,
                )
            return ConversationHandler.END
        if not ban or not ban.get("is_active"):
            await reply_rich(
                msg,
                t("appeals.submit.invalid_link", locale, plain=True),
                log_label=f"Appeal invalid-link for ban_id={ban_id}",
                parse_mode=None,
            )
            return ConversationHandler.END
        if ban.get("target_user_id") != uid:
            await reply_rich(
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
                    # * The stale card is released together with the
                    # * appeal it belongs to, so the open appeal does
                    # * not keep the decision occupied.
                    await db.bans_db.release_stale_review(
                        ban_id, int(ban.get("review_message_id") or 0)
                    )
                except Exception:
                    log.exception(
                        "Appeal _start: failed to clear stale review for ban_id=%s user=%d",
                        ban_id,
                        uid,
                    )
                    with contextlib.suppress(Exception):
                        await reply_rich(
                            msg,
                            t(
                                "appeals.submit.pending_review",
                                locale,
                                hours=_STALE_REVIEW_HOURS,
                                plain=True,
                            ),
                            parse_mode=None,
                        )
                    return ConversationHandler.END
                log.info(
                    "Appeal _start: stale review cleared for ban_id=%s user=%d",
                    ban_id,
                    uid,
                )
            else:
                await reply_rich(
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
            await reply_rich(
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
        scope = flow_scope(ctx)
        scope["appeal_ban_id"] = ban_id
        scope["appeal_log_msg_id"] = ban.get("log_message_id", 0)
        try:
            log_display = await display_community_link(ctx.bot, self.log_channel)
            instr = await reply_rich_result(
                msg,
                self.instruction_text(locale, log_display),
                reply_markup=appeal_cancel_btn(None, self.cancel_callback, locale),
            )
            scope["appeal_instruction_msg_id"] = instr.id
        except Exception as exc:
            log.debug("Appeal instruction send failed for user %d: %s", uid, exc)
            clear_appeal_state(scope)
            return ConversationHandler.END
        return WAITING_APPEAL

    async def _on_entry(self, ctx: Ctx) -> int:
        """Entry-point handler; parses the /start appeal deep link."""
        msg = ctx.effective_message
        if msg is None or msg.text is None:
            return ConversationHandler.END
        m = _ID_RE.match(msg.text.strip())
        if not m:
            return ConversationHandler.END
        return await self._start(ctx, m.group(1))

    async def on_group_appeal(self, ctx: Ctx) -> None:
        """Handle #appeal in the main group via the DM submit path."""
        await handle_group_appeal(ctx, self._on_message)

    async def _on_cancel(self, ctx: Ctx) -> int | None:
        """Cancel button handler; clears state and ends the conversation."""
        q = ctx.callback_query
        if q is None:
            return ConversationHandler.END
        scope = flow_scope(ctx)
        live_mid = scope.get("appeal_instruction_msg_id")
        tap_mid = q.message.id if q.message is not None else None
        if live_mid is not None and tap_mid is not None and tap_mid != live_mid:
            try:
                await q.answer()
            except Exception as exc:
                log.debug("appeal stale-cancel answer failed: %s", exc)
            # * A stale card must not end the live appeal opened by a newer
            # * deep link; leave its conversation and scope untouched.
            return None
        clear_appeal_state(scope)
        try:
            await q.answer()
        except Exception as exc:
            log.debug("appeal cancel answer failed: %s", exc)
        try:
            locale = await locale_for_update(ctx)
            await safe_edit_cb(
                q,
                t("appeals.submit.cancelled", locale, plain=True),
                parse_mode=None,
            )
        except Exception:
            log.debug("appeal cancel edit failed (message may already be gone)")
        return ConversationHandler.END

    async def _end(self, ctx: Ctx) -> int:
        """Fallback handler; fires on any unrecognised command."""
        scope = flow_scope(ctx)
        if not scope.get("appeal_ban_id"):
            # * This fallback is flattened into group 0 and matches every
            # * prefixed command. An unknown command with no live appeal must
            # * reach the next flow's fallback, so a stale ban proof session
            # * can still be cleaned up instead of being left on screen.
            raise ContinuePropagation()
        clear_appeal_state(scope)
        msg = ctx.effective_message
        if msg:
            await reply_rich(
                msg,
                t(
                    "appeals.submit.session_ended",
                    await locale_for_update(ctx),
                    plain=True,
                ),
                log_label="Appeal _end",
                parse_mode=None,
            )
        return ConversationHandler.END

    async def _on_unexpected(self, ctx: Ctx) -> int:
        """Non-text message handler; nudge back to text."""
        if not flow_scope(ctx).get("appeal_ban_id"):
            # * Flat registration exposes this private-chat handler even while
            # * another flow owns the update. Pass media back to its owner.
            raise ContinuePropagation()
        msg = ctx.effective_message
        if msg is not None:
            await reply_rich(
                msg,
                t(
                    "appeals.submit.unexpected",
                    await locale_for_update(ctx),
                    plain=True,
                ),
                log_label="Appeal unexpected-type",
                parse_mode=None,
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
                    filters.private & filters.text & ~ALL_PREFIXES_CMD_FILTER,
                    on_message,
                ),
                MessageHandler(
                    filters.private & ~filters.text & ~ALL_PREFIXES_CMD_FILTER,
                    on_unexpected,
                ),
            ],
        },
        fallbacks=[
            # * Other commands pass through so the user is not trapped in an
            # * appeal they want to leave.
            MessageHandler(
                ALL_PREFIXES_CMD_FILTER & ~build_conversation_escape_filter(),
                on_end,
            ),
        ],
        per_chat=True,
        per_user=True,
        per_message=False,
    )


@dataclass(frozen=True)
class BuildAppeal(AppealSubmitMixin, AppealReviewMixin):
    """Configurable appeal ConversationHandler builder."""

    community_name: str
    log_channel: int
    cancel_label: str = field(default="Cancel", kw_only=True)
    cancel_callback: str = field(default="cancel_appeal", kw_only=True)


appeal = BuildAppeal(cfg.community_name, cfg.logs[0])
