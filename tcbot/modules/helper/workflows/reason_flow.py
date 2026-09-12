# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Central reason-step infrastructure."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import KeyboardButtonStyle
from telegram.ext import (
    CallbackQueryHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from tcbot.modules.helper import replies
from tcbot.modules.helper.locale import locale_for_update
from tcbot.modules.helper.parse_editmsg import safe_reply
from tcbot.modules.helper.workflows.proof_flow import PROOF_MEDIA_FILTER, BuildProof
from tcbot.utils.formatter import bold, esc, mention
from tcbot.utils.i18n import Safe, t
from tcbot.utils.prefixes import ALL_PREFIXES_CMD_FILTER

if TYPE_CHECKING:
    from collections.abc import Callable

from telegram.ext.filters import BaseFilter

log = logging.getLogger(__name__)

# * State constants used by all moderation ConversationHandlers
WAITING_REASON = 0
WAITING_PROOF = 1

# * Maximum characters accepted for a moderation reason.
# * Telegram hard-caps messages at 4096 chars; action summaries include names,
# * IDs, and other metadata on top of the reason.  1000 chars is generous for
# * any real reason while guaranteeing the combined message stays under the cap.
# * Public name so command entries can fail fast on overlong inline reasons
# * without paying for target resolution or DB work first.
MAX_REASON_LEN: int = 1000

_MAX_REASON_LEN: int = MAX_REASON_LEN


# ───────────────────────── Reason parsing ───────────────────────── #


def parse_inline_reason(
    args: list[str],
    *,
    has_explicit_target: bool,
    reply_target_id: int | None = None,
) -> str:
    """Extract any inline reason text from command arguments.

    With an explicit target the first token names the target, so the
    reason starts at ``args[1:]``. On the reply-wins path every arg is
    reason text, with one exception: a leading numeric token equal to
    ``reply_target_id`` is the target restated (e.g. reply + ``/tcb
    1419172317 spamming`` aimed at 1419172317), not reason content, so it
    is dropped. A leading numeric token naming anyone else stays in the
    reason. Pass ``None`` (the default) whenever the entry is not on the
    reply-wins path.
    """
    tokens = args[1:] if has_explicit_target else args
    if (
        reply_target_id is not None
        and not has_explicit_target
        and tokens
        and tokens[0].lstrip("-").isdigit()
        and int(tokens[0]) == reply_target_id
    ):
        tokens = tokens[1:]
    return " ".join(tokens).strip()


def is_reason_too_long(text: str) -> bool:
    """Return True when ``text`` exceeds the shared reason length cap."""
    return len(text) > MAX_REASON_LEN


def reason_too_long_text(actual_len: int, locale: str | None = None) -> str:
    """Single source of truth for the overlong-reason reply text."""
    return t(
        "reason.limit.text",
        locale,
        max=MAX_REASON_LEN,
        actual=actual_len,
        plain=True,
    )


# ─────────────────────────── BuildReason ────────────────────────── #


@dataclass(frozen=True)
class BuildReason:
    """Configurable reason-step keyboard and prompt builder."""

    action: str
    skip_allowed: bool = field(default=True, kw_only=True)
    skip_label: str = field(default="Skip", kw_only=True)
    cancel_label: str = field(default="Cancel", kw_only=True)

    def keyboard(self, locale: str | None = None) -> InlineKeyboardMarkup:
        """Reason-step keyboard. Includes Skip only when skip_allowed is True."""
        buttons: list[InlineKeyboardButton] = []
        if self.skip_allowed:
            buttons.append(
                InlineKeyboardButton(
                    t("button.skip", locale, plain=True),
                    callback_data=f"{self.action}_skip_reason",
                    style=KeyboardButtonStyle.PRIMARY,
                )
            )
        buttons.append(
            InlineKeyboardButton(
                t("button.cancel", locale, plain=True),
                callback_data=f"{self.action}_cancel",
            )
        )
        return InlineKeyboardMarkup([buttons])

    def prompt(
        self,
        target_mention: str,
        action_label: str,
        extra_info: str = "",
        locale: str | None = None,
    ) -> str:
        """Prompt asking the moderator to type a reason."""
        # * target_mention/extra_info must already be MarkdownV2-ready
        # * (mention/code/bold output): the single producer (muting.py
        # * code() ID plus fmt_duration) is verified, so no re-escaping here.
        suffix = Safe(f" {extra_info}") if extra_info else Safe("")
        skip_hint = (
            Safe("")
            if not self.skip_allowed
            else Safe(
                t(
                    "reason.hint.skip",
                    locale,
                    label=Safe(bold(t("button.skip", locale, plain=True))),
                )
            )
        )
        return t(
            "reason.prompt.body",
            locale,
            verb=t(f"proof.action.{action_label}.verb", locale, plain=True),
            target=Safe(target_mention),
            suffix=suffix,
            skip_hint=skip_hint,
        )


# ─────────────── Generic ConversationHandler factory ────────────── #


class _ModActionFlow:
    """Per-action ConversationHandler state and callback container.

    Replaces the previous closure-heavy ``build_modaction_conv`` body so that
    each handler is a named method on an explicit state object.  This keeps the
    public factory function under 10 lines and makes individual handlers
    testable without reproducing the full closure environment.
    """

    def __init__(
        self,
        action: str,
        reason: BuildReason,
        proof: BuildProof,
        executor: Callable[..., Any],
    ) -> None:
        self.action = action
        self.reason = reason
        self.proof = proof
        self.executor = executor
        self._reason_key = f"{action}_reason"
        self._proof_msgs_key = f"{action}_proof_msgs"
        self._extra_info_key = f"{action}_extra_info"
        self._prompt_chat_key = f"{action}_prompt_chat"
        self._prompt_id_key = f"{action}_prompt_id"
        self._exec_key = f"{action}_executing"

    # ── Helpers ───────────────────────────────────────────────────── #

    def _get_target(self, ctx: ContextTypes.DEFAULT_TYPE, locale: str | None) -> str:
        if ctx.user_data is None:
            return t("reason.target.fallback", locale, plain=True)
        raw: str = (
            ctx.user_data.get(f"{self.action}_target_name")
            or ctx.user_data.get(f"{self.action}_target_fname")
            or t("reason.target.fallback", locale, plain=True)
        )
        tid: int | None = ctx.user_data.get(f"{self.action}_target_id")
        if tid:
            return mention(tid, raw)
        return esc(raw)

    def _clear_user_data(self, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        """Remove all ``{action}_*`` keys from user_data on cancel / timeout."""
        if ctx.user_data is None:
            return
        prefix = f"{self.action}_"
        for key in [k for k in ctx.user_data if k.startswith(prefix)]:
            ctx.user_data.pop(key, None)

    # ── WAITING_REASON handlers ──────────────────────────────────── #

    async def _on_reason_text(
        self, update: Update, ctx: ContextTypes.DEFAULT_TYPE
    ) -> int:
        msg = update.effective_message
        if msg is None or msg.text is None:
            return WAITING_REASON
        if ctx.user_data is None:
            return WAITING_REASON

        text = msg.text.strip()
        if is_reason_too_long(text):
            await safe_reply(
                msg,
                reason_too_long_text(len(text), await locale_for_update(update)),
                log_label=f"{self.action} reason-too-long",
                parse_mode=None,
            )
            return WAITING_REASON

        ctx.user_data[self._reason_key] = text
        extra_info = ctx.user_data.get(self._extra_info_key, "")
        locale = await locale_for_update(update)
        prompt_txt = self.proof.step_prompt(
            self._get_target(ctx, locale), self.action, text, extra_info, locale
        )
        prompt_chat = ctx.user_data.get(self._prompt_chat_key)
        prompt_id = ctx.user_data.get(self._prompt_id_key)
        prompt_sent = False
        if prompt_id is not None and prompt_chat is not None:
            try:
                await ctx.bot.edit_message_text(
                    prompt_txt,
                    chat_id=prompt_chat,
                    message_id=prompt_id,
                    parse_mode="MarkdownV2",
                    reply_markup=self.proof.keyboard(locale),
                )
                prompt_sent = True
            except Exception:
                log.exception("%s prompt edit failed (reason step)", self.action)
        else:
            try:
                await msg.reply_text(
                    prompt_txt,
                    parse_mode="MarkdownV2",
                    reply_markup=self.proof.keyboard(locale),
                )
                prompt_sent = True
            except Exception as exc:
                log.debug("%s reason-text fallback reply failed: %s", self.action, exc)
        if not prompt_sent:
            self._clear_user_data(ctx)
            return ConversationHandler.END
        return WAITING_PROOF

    async def _on_skip_reason(
        self, update: Update, ctx: ContextTypes.DEFAULT_TYPE
    ) -> int:
        q = update.callback_query
        if q is None or ctx.user_data is None:
            return WAITING_REASON

        locale = await locale_for_update(update)
        ctx.user_data[self._reason_key] = replies.no_reason(locale, plain=True)
        extra_info = ctx.user_data.get(self._extra_info_key, "")
        prompt_txt = self.proof.step_prompt(
            self._get_target(ctx, locale),
            self.action,
            replies.no_reason(locale, plain=True),
            extra_info,
            locale,
        )
        results = await asyncio.gather(
            q.answer(),
            q.edit_message_text(
                prompt_txt,
                parse_mode="MarkdownV2",
                reply_markup=self.proof.keyboard(locale),
            ),
            return_exceptions=True,
        )
        if isinstance(results[1], BaseException):
            log.debug(
                "%s prompt edit failed (skip-reason step): %s", self.action, results[1]
            )
            # * Proof prompt is invisible; clear state to avoid locking
            # * them in WAITING_PROOF with no visible UI element to interact with.
            self._clear_user_data(ctx)
            return ConversationHandler.END
        return WAITING_PROOF

    # ── WAITING_PROOF handlers ───────────────────────────────────── #

    async def _on_proof(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
        msg = update.effective_message
        if msg is None or ctx.user_data is None:
            return WAITING_PROOF

        # * Double-submit guard: Done, Skip, or a racing duplicate is
        # * already running the executor. Discard this update silently.
        if ctx.user_data.get(self._exec_key):
            return ConversationHandler.END

        # * Buffer every proof item (album parts arrive as separate updates;
        # * sequential sends accumulate too). Execution waits for the Done
        # * button below, so multi-photo/video/GIF/file proof lands whole.
        if msg.photo or msg.video or msg.animation or msg.document:
            existing: list = ctx.user_data.get(self._proof_msgs_key, [])
            ctx.user_data[self._proof_msgs_key] = [*existing, msg]
        return WAITING_PROOF

    async def _on_done_proof(
        self, update: Update, ctx: ContextTypes.DEFAULT_TYPE
    ) -> int:
        """Execute with everything collected once the moderator taps Done."""
        q = update.callback_query
        if q is None or ctx.user_data is None:
            return ConversationHandler.END
        locale = await locale_for_update(update)
        msgs: list = ctx.user_data.get(self._proof_msgs_key, [])
        if not msgs:
            # * Nothing collected: nudge instead of silently skipping
            # * (Skip exists for that) or executing an empty proof.
            try:
                await q.answer(
                    t(
                        "proof.empty.body",
                        locale,
                        done=t("button.done", locale, plain=True),
                        plain=True,
                    ),
                    show_alert=True,
                )
            except Exception as exc:
                log.debug("%s done-proof empty answer failed: %s", self.action, exc)
            return WAITING_PROOF
        if ctx.user_data.get(self._exec_key):
            try:
                await q.answer()
            except Exception as exc:
                log.debug("%s done-proof dup q.answer failed: %s", self.action, exc)
            return ConversationHandler.END
        # * Set the executing flag before the first await to close the race
        # * window; the update here is the live Done tap, so the executor
        # * below never touches a stale stored Update object.
        ctx.user_data[self._exec_key] = True
        try:
            await q.answer()
        except Exception as exc:
            log.debug("%s done-proof q.answer failed: %s", self.action, exc)
        try:
            await self.executor(update, ctx)
        except BaseException:
            # * Mirror the old immediate contract: clear state before
            # * propagating so a failed executor does not leak keys.
            # * CancelledError is re-raised unchanged.
            self._clear_user_data(ctx)
            raise
        self._clear_user_data(ctx)
        return ConversationHandler.END

    async def _on_skip_proof(
        self, update: Update, ctx: ContextTypes.DEFAULT_TYPE
    ) -> int:
        q = update.callback_query
        if q is None or ctx.user_data is None:
            return WAITING_PROOF

        # * Double-submit guard: user tapped Skip twice before the first call
        # * returned END.  Acknowledge and discard the duplicate.
        if ctx.user_data.get(self._exec_key):
            try:
                await q.answer()
            except Exception as exc:
                log.debug("%s skip-proof dup q.answer failed: %s", self.action, exc)
            return ConversationHandler.END
        ctx.user_data[self._exec_key] = True

        # * The executor may raise (DB outage, Telegram API failure on a DM,
        # * a runtime bug). The q.answer() must always run; the executor
        # * exception must NOT be silently discarded -- PTB's global error
        # * handler reports it to LOGS_ERRORS. We gather them in parallel
        # * for speed but inspect the executor result and re-raise if it
        # * failed. The q.answer() is best-effort: its failure is logged
        # * at debug and does not block the executor failure propagation.
        qa_result, exec_result = await asyncio.gather(
            q.answer(),
            self.executor(update, ctx),
            return_exceptions=True,
        )
        if isinstance(qa_result, BaseException):
            log.debug("%s skip-proof q.answer failed: %s", self.action, qa_result)
        if isinstance(exec_result, BaseException):
            # * Surface the executor failure to PTB's error handler instead
            # * of swallowing it. Re-raise after clearing state so the
            # * conversation is properly ended.
            self._clear_user_data(ctx)
            raise exec_result
        self._clear_user_data(ctx)
        return ConversationHandler.END

    # ── Cancel / fallback ────────────────────────────────────────── #

    async def _on_reason_unexpected(
        self, update: Update, ctx: ContextTypes.DEFAULT_TYPE
    ) -> int:
        """Reject non-text messages during reason collection."""
        if update.effective_message:
            locale = await locale_for_update(update)
            await safe_reply(
                update.effective_message,
                t(
                    "reason.unexpected.body",
                    locale,
                    action=self.action,
                    skip=t("button.skip", locale, plain=True),
                    cancel=t("button.cancel", locale, plain=True),
                    plain=True,
                ),
                log_label=f"{self.action} reason-unexpected",
                parse_mode=None,
            )
        return WAITING_REASON

    async def _on_proof_unexpected(
        self, update: Update, ctx: ContextTypes.DEFAULT_TYPE
    ) -> int:
        """Reject unexpected message types during proof collection."""
        if update.effective_message:
            locale = await locale_for_update(update)
            await safe_reply(
                update.effective_message,
                t(
                    "proof.unexpected.body",
                    locale,
                    skip=t("button.skip", locale, plain=True),
                    cancel=t("button.cancel", locale, plain=True),
                    plain=True,
                ),
                log_label=f"{self.action} proof-unexpected",
                parse_mode=None,
            )
        return WAITING_PROOF

    async def _on_cancel(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
        q = update.callback_query
        if q is None:
            return ConversationHandler.END

        self._clear_user_data(ctx)
        locale = await locale_for_update(update)
        results = await asyncio.gather(
            q.answer(),
            q.edit_message_text(
                t("reason.cancel.body", locale, action=self.action, plain=True)
            ),
            return_exceptions=True,
        )
        if isinstance(results[1], BaseException):
            log.debug(
                "%s cancel edit failed (message may already be gone): %s",
                self.action,
                results[1],
            )
        return ConversationHandler.END

    async def _on_end_conv(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
        self._clear_user_data(ctx)
        if update.effective_message:
            locale = await locale_for_update(update)
            await safe_reply(
                update.effective_message,
                t(
                    "reason.cancel.via_command",
                    locale,
                    Action=self.action.capitalize(),
                    plain=True,
                ),
                log_label=f"{self.action} cancel-via-command",
                parse_mode=None,
            )
        return ConversationHandler.END

    # ── Build states ─────────────────────────────────────────────── #

    def build(
        self,
        entry_fn: Callable[..., Any],
        entry_filter: BaseFilter,
        escape_filter: BaseFilter | None = None,
    ) -> ConversationHandler:
        """Assemble the ConversationHandler from bound callbacks."""
        reason_state: list = [
            MessageHandler(
                filters.TEXT & ~ALL_PREFIXES_CMD_FILTER, self._on_reason_text
            ),
            CallbackQueryHandler(self._on_cancel, pattern=rf"^{self.action}_cancel$"),
            MessageHandler(
                ~filters.TEXT & ~ALL_PREFIXES_CMD_FILTER,
                self._on_reason_unexpected,
            ),
        ]
        if self.reason.skip_allowed:
            reason_state.insert(
                1,
                CallbackQueryHandler(
                    self._on_skip_reason,
                    pattern=rf"^{self.action}_skip_reason$",
                ),
            )

        proof_state = [
            MessageHandler(PROOF_MEDIA_FILTER, self._on_proof),
            CallbackQueryHandler(
                self._on_skip_proof, pattern=rf"^{self.action}_skip_proof$"
            ),
            CallbackQueryHandler(
                self._on_done_proof, pattern=rf"^{self.action}_done_proof$"
            ),
            CallbackQueryHandler(self._on_cancel, pattern=rf"^{self.action}_cancel$"),
            MessageHandler(
                ~PROOF_MEDIA_FILTER & ~ALL_PREFIXES_CMD_FILTER,
                self._on_proof_unexpected,
            ),
        ]

        fallback_filter = ALL_PREFIXES_CMD_FILTER
        if escape_filter is not None:
            fallback_filter = fallback_filter & ~escape_filter

        return ConversationHandler(
            entry_points=[MessageHandler(entry_filter, entry_fn)],
            states={
                WAITING_REASON: reason_state,
                WAITING_PROOF: proof_state,
            },
            fallbacks=[
                CallbackQueryHandler(
                    self._on_cancel, pattern=rf"^{self.action}_cancel$"
                ),
                MessageHandler(fallback_filter, self._on_end_conv),
            ],
            per_user=True,
            per_chat=True,
            per_message=False,
        )


def build_modaction_conv(
    reason: BuildReason,
    proof: BuildProof,
    entry_fn: Callable[..., Any],
    executor: Callable[..., Any],
    entry_filter: BaseFilter,
    escape_filter: BaseFilter | None = None,
) -> ConversationHandler:
    """Build a generic reason + proof ConversationHandler."""
    return _ModActionFlow(reason.action, reason, proof, executor).build(
        entry_fn, entry_filter, escape_filter
    )
