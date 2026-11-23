# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Central reason-step infrastructure."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from telegram import InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackQueryHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)
from telegram.ext.filters import BaseFilter

from tcbot import database as db
from tcbot.modules.helper import guards
from tcbot.modules.helper.buttons import reason_step_btn
from tcbot.modules.helper.buttons import rules as rules_btn
from tcbot.modules.helper.extraction import parse_user_id_token
from tcbot.modules.helper.locale import locale_for_update
from tcbot.modules.helper.messages import (
    replies,
    reply_rich,
    reply_rich_result,
    safe_edit_cb,
    safe_edit_message,
)
from tcbot.modules.helper.pipelines import rules_step
from tcbot.modules.helper.pipelines.proof_flow import (
    PROOF_MEDIA_FILTER,
    BuildProof,
)
from tcbot.modules.helper.scope import (
    callback_is_current,
    clear_flow_scope,
    flow_scope,
)
from tcbot.utils.dispatch import throw_if_cancelled
from tcbot.utils.i18n import Safe, bold, esc, t, user_ref
from tcbot.utils.logger import get_logger
from tcbot.utils.prefixes import (
    ALL_PREFIXES_CMD_FILTER,
    build_conversation_escape_filter,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from tcbot.database.users_roles import RoleName

log = get_logger(__name__)


def rules_from_scope(
    scope: dict[str, Any], action: str
) -> tuple[list[int], str | None]:
    """Return the rule ids and optional note collected by the picker."""
    return list(scope.get(f"{action}_rules", [])), scope.get(f"{action}_rules_note")


# ───────────────────────── Reason parsing ───────────────────────── #


WAITING_REASON = 0
WAITING_PROOF = 1
WAITING_RULES = 2
WAITING_RULES_NOTE = 3

MAX_REASON_LEN: int = 1000
MAX_RULES_NOTE_LEN: int = 200

# * Re-entry commands of each moderation flow. They stay in the fallback so
# * starting the same action again still ends the previous conversation.
_OWN_COMMANDS: dict[str, tuple[str, ...]] = {
    "kick": ("tckick", "tck"),
    "mute": ("tcmute", "tcm"),
    "warn": ("tcwarn", "tcw"),
}


def parse_inline_reason(
    args: list[str],
    *,
    has_explicit_target: bool,
    reply_target_id: int | None = None,
) -> str:
    """Extract any inline reason text from command arguments."""
    tokens = args[1:] if has_explicit_target else args
    if (
        reply_target_id is not None
        and not has_explicit_target
        and tokens
        and parse_user_id_token(tokens[0]) == reply_target_id
    ):
        tokens = tokens[1:]
    return " ".join(tokens).strip()


def is_reason_too_long(text: str) -> bool:
    """Return True when the text exceeds the shared reason length cap."""
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


# ───────────────────────── Reason builder ───────────────────────── #


@dataclass(frozen=True)
class BuildReason:
    """Configurable reason-step keyboard and prompt builder."""

    action: str
    skip_allowed: bool = field(default=True, kw_only=True)

    def keyboard(self, locale: str | None = None) -> InlineKeyboardMarkup:
        """Return the reason-step keyboard (Skip only when allowed)."""
        return reason_step_btn(
            self.action, skip_allowed=self.skip_allowed, locale=locale
        )

    def prompt(
        self,
        target_mention: str,
        action_label: str,
        extra_info: str = "",
        locale: str | None = None,
    ) -> str:
        """Prompt asking the moderator to type a reason."""
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


# ──────────────────────── Shared flow state ─────────────────────── #


class _FlowBase:
    """Shared conversation state plus cancel and fallback handlers."""

    def __init__(
        self,
        action: str,
        reason: BuildReason,
        proof: BuildProof,
        executor: Callable[..., Any],
        min_role: RoleName,
        *,
        rules_enabled: bool = False,
    ) -> None:
        self.action = action
        self.reason = reason
        self.proof = proof
        self.executor = executor
        self.min_role: RoleName = min_role
        self.rules_enabled = rules_enabled
        self._reason_key = f"{action}_reason"
        self._rules_key = f"{action}_rules"
        self._rules_note_key = f"{action}_rules_note"
        self._proof_msgs_key = f"{action}_proof_msgs"
        self._extra_info_key = f"{action}_extra_info"
        self._prompt_chat_key = f"{action}_prompt_chat"
        self._prompt_id_key = f"{action}_prompt_id"
        self._exec_key = f"{action}_executing"

    def _get_target(self, scope: dict[str, Any], locale: str | None) -> str:
        raw: str = (
            scope.get(f"{self.action}_target_name")
            or scope.get(f"{self.action}_target_fname")
            or t("reason.target.fallback", locale, plain=True)
        )
        tid: int | None = scope.get(f"{self.action}_target_id")
        if tid:
            return user_ref(tid, raw)
        return esc(raw)

    async def _edit_prompt(
        self,
        update: Update,
        ctx: ContextTypes.DEFAULT_TYPE,
        text: str,
        markup: InlineKeyboardMarkup,
    ) -> bool:
        """Edit the shared prompt message, replying when it cannot be edited."""
        scope = flow_scope(ctx, update)
        chat_id = scope.get(self._prompt_chat_key)
        message_id = scope.get(self._prompt_id_key)
        try:
            if chat_id is not None and message_id is not None:
                await safe_edit_message(
                    ctx.bot, chat_id, message_id, text, reply_markup=markup
                )
            else:
                msg = update.effective_message
                if msg is None:
                    return False
                await reply_rich_result(msg, text, reply_markup=markup)
            return True
        except Exception as exc:
            log.debug("%s prompt edit failed: %s", self.action, exc)
            return False

    async def _show_proof_prompt(
        self, update: Update, ctx: ContextTypes.DEFAULT_TYPE, prompt_txt: str
    ) -> int:
        """Render the proof prompt and enter the proof state."""
        locale = await locale_for_update(update)
        if not await self._edit_prompt(
            update, ctx, prompt_txt, self.proof.keyboard(locale)
        ):
            self._clear_scope(ctx, update)
            return ConversationHandler.END
        return WAITING_PROOF

    def _callback_is_live(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> bool:
        """Reject a tap on a button left behind by an earlier flow."""
        return callback_is_current(
            update,
            flow_scope(ctx, update),
            chat_key=self._prompt_chat_key,
            message_key=self._prompt_id_key,
        )

    async def _ignore_stale_callback(self, update: Update) -> None:
        """Acknowledge a stale tap without touching the current flow."""
        query = update.callback_query
        if query is None:
            return
        try:
            await query.answer()
        except Exception as exc:
            log.debug("%s stale callback answer failed: %s", self.action, exc)

    def _clear_scope(self, ctx: ContextTypes.DEFAULT_TYPE, update: Update) -> None:
        """Remove all action keys from the conversation scope.

        Only this action's keys go: another flow may hold its own payload
        in the same conversation scope.
        """
        scope = flow_scope(ctx, update)
        prefix = f"{self.action}_"
        clear_flow_scope(ctx, update, keys=[k for k in scope if k.startswith(prefix)])

    async def _recheck_tapper(
        self, update: Update, ctx: ContextTypes.DEFAULT_TYPE
    ) -> bool:
        """Re-verify the tapper still meets min_role."""
        q = update.callback_query
        tap_user = update.effective_user
        tap_msg = update.effective_message
        if tap_user is None or tap_msg is None:
            if q is not None:
                try:
                    await q.answer()
                except Exception as exc:
                    log.debug("%s recheck q.answer failed: %s", self.action, exc)
            return False
        if await guards.recheck_executor_rank(
            tap_msg, tap_user.id, min_role=self.min_role
        ):
            return True
        if q is not None:
            try:
                await q.answer()
            except Exception as exc:
                log.debug("%s recheck q.answer failed: %s", self.action, exc)
        self._clear_scope(ctx, update)
        return False

    async def _on_cancel(
        self, update: Update, ctx: ContextTypes.DEFAULT_TYPE
    ) -> int | None:
        q = update.callback_query
        if q is None:
            return ConversationHandler.END
        if not self._callback_is_live(update, ctx):
            await self._ignore_stale_callback(update)
            return None
        self._clear_scope(ctx, update)
        locale = await locale_for_update(update)
        results = await asyncio.gather(
            q.answer(),
            safe_edit_cb(
                q,
                t("reason.cancel.body", locale, action=self.action, plain=True),
                reply_markup=None,
                parse_mode=None,
            ),
            return_exceptions=True,
        )
        throw_if_cancelled(results)
        if isinstance(results[1], BaseException):
            log.debug(
                "%s cancel edit failed (message may already be gone): %s",
                self.action,
                results[1],
            )
        return ConversationHandler.END

    async def _on_end_conv(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
        self._clear_scope(ctx, update)
        if update.effective_message:
            locale = await locale_for_update(update)
            await reply_rich(
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


# ─────────────────────────── Proof step ─────────────────────────── #


class _ProofStepMixin(_FlowBase):
    """Proof buffer, Done/Skip execution, and unexpected handlers."""

    async def _on_proof(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
        msg = update.effective_message
        if msg is None or ctx.user_data is None:
            return WAITING_PROOF
        scope = flow_scope(ctx, update)
        if scope.get(self._exec_key):
            return ConversationHandler.END
        if msg.photo or msg.video or msg.animation or msg.document:
            existing: list = scope.get(self._proof_msgs_key, [])
            scope[self._proof_msgs_key] = [*existing, msg]
        return WAITING_PROOF

    async def _on_done_proof(
        self, update: Update, ctx: ContextTypes.DEFAULT_TYPE
    ) -> int | None:
        """Execute with everything collected once the moderator taps Done."""
        q = update.callback_query
        if q is None or ctx.user_data is None:
            return ConversationHandler.END
        if not self._callback_is_live(update, ctx):
            await self._ignore_stale_callback(update)
            return None
        scope = flow_scope(ctx, update)
        locale = await locale_for_update(update)
        msgs: list = scope.get(self._proof_msgs_key, [])
        if not msgs:
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
        if scope.get(self._exec_key):
            try:
                await q.answer()
            except Exception as exc:
                log.debug("%s done-proof dup q.answer failed: %s", self.action, exc)
            return ConversationHandler.END
        # * Claim the execution slot before the first await. The flag is the
        # * only replay guard and two taps on the same button can be
        # * processed concurrently, so claiming it after the role recheck
        # * would let both taps through and the loser would run with an
        # * empty target.
        scope[self._exec_key] = True
        if not await self._recheck_tapper(update, ctx):
            scope.pop(self._exec_key, None)
            return ConversationHandler.END
        try:
            await q.answer()
        except Exception as exc:
            log.debug("%s done-proof q.answer failed: %s", self.action, exc)
        try:
            await self.executor(update, ctx)
        except BaseException:
            self._clear_scope(ctx, update)
            raise
        self._clear_scope(ctx, update)
        return ConversationHandler.END

    async def _on_skip_proof(
        self, update: Update, ctx: ContextTypes.DEFAULT_TYPE
    ) -> int | None:
        q = update.callback_query
        if q is None or ctx.user_data is None:
            return WAITING_PROOF
        if not self._callback_is_live(update, ctx):
            await self._ignore_stale_callback(update)
            return None
        scope = flow_scope(ctx, update)
        if scope.get(self._exec_key):
            try:
                await q.answer()
            except Exception as exc:
                log.debug("%s skip-proof dup q.answer failed: %s", self.action, exc)
            return ConversationHandler.END
        # * Claim the execution slot before the first await, exactly like the
        # * Done button does, so a concurrent double tap cannot run the
        # * executor twice.
        scope[self._exec_key] = True
        if not await self._recheck_tapper(update, ctx):
            scope.pop(self._exec_key, None)
            return ConversationHandler.END
        qa_result, exec_result = await asyncio.gather(
            q.answer(),
            self.executor(update, ctx),
            return_exceptions=True,
        )
        throw_if_cancelled((qa_result, exec_result))
        if isinstance(qa_result, BaseException):
            log.debug("%s skip-proof q.answer failed: %s", self.action, qa_result)
        if isinstance(exec_result, BaseException):
            self._clear_scope(ctx, update)
            raise exec_result
        self._clear_scope(ctx, update)
        return ConversationHandler.END

    async def _on_proof_unexpected(
        self, update: Update, ctx: ContextTypes.DEFAULT_TYPE
    ) -> int:
        """Reject unexpected message types during proof collection."""
        if update.effective_message:
            locale = await locale_for_update(update)
            await reply_rich(
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


# ─────────────────────────── Reason step ────────────────────────── #


class _ReasonStepMixin(_FlowBase):
    """Reason-text, skip-reason, and unexpected handlers."""

    async def _on_reason_text(
        self, update: Update, ctx: ContextTypes.DEFAULT_TYPE
    ) -> int:
        msg = update.effective_message
        if msg is None or msg.text is None:
            return WAITING_REASON
        if ctx.user_data is None:
            return WAITING_REASON
        if not await self._recheck_tapper(update, ctx):
            return ConversationHandler.END
        scope = flow_scope(ctx, update)
        text = msg.text.strip()
        locale = await locale_for_update(update)
        if not text:
            # * filters.TEXT accepts whitespace-only messages, and the
            # * database rejects a blank reason. Keep the flow open instead
            # * of storing "".
            await reply_rich(
                msg,
                t("reason.empty.text", locale, plain=True),
                log_label=f"{self.action} reason-empty",
                parse_mode=None,
            )
            return WAITING_REASON
        if is_reason_too_long(text):
            await reply_rich(
                msg,
                reason_too_long_text(len(text), locale),
                log_label=f"{self.action} reason-too-long",
                parse_mode=None,
            )
            return WAITING_REASON
        scope[self._reason_key] = text
        extra_info = scope.get(self._extra_info_key, "")
        prompt_txt = self.proof.step_prompt(
            self._get_target(scope, locale), self.action, text, extra_info, locale
        )
        return await self._after_reason(update, ctx, prompt_txt)

    async def _on_skip_reason(
        self, update: Update, ctx: ContextTypes.DEFAULT_TYPE
    ) -> int | None:
        q = update.callback_query
        if q is None or ctx.user_data is None:
            return WAITING_REASON
        if not self._callback_is_live(update, ctx):
            await self._ignore_stale_callback(update)
            return None
        if not await self._recheck_tapper(update, ctx):
            return ConversationHandler.END
        scope = flow_scope(ctx, update)
        locale = await locale_for_update(update)
        scope[self._reason_key] = replies.no_reason(locale, plain=True)
        extra_info = scope.get(self._extra_info_key, "")
        prompt_txt = self.proof.step_prompt(
            self._get_target(scope, locale),
            self.action,
            replies.no_reason(locale, plain=True),
            extra_info,
            locale,
        )
        results = await asyncio.gather(
            q.answer(),
            safe_edit_cb(
                q,
                prompt_txt,
                reply_markup=self.proof.keyboard(locale),
            ),
            return_exceptions=True,
        )
        throw_if_cancelled(results)
        if isinstance(results[1], BaseException):
            log.debug(
                "%s prompt edit failed (skip-reason step): %s", self.action, results[1]
            )
            self._clear_scope(ctx, update)
            return ConversationHandler.END
        return await self._after_reason(update, ctx, prompt_txt)

    async def _after_reason(
        self, update: Update, ctx: ContextTypes.DEFAULT_TYPE, prompt_txt: str
    ) -> int:
        """Move to the rules picker when rules exist, otherwise to proof."""
        scope = flow_scope(ctx, update)
        scope[self._rules_key] = []
        locale = await locale_for_update(update)
        if self.rules_enabled:
            uid = update.effective_user.id if update.effective_user else 0
            try:
                may_pick = await db.users_roles.has_permission(uid, "rules.view")
            except Exception as exc:
                log.warning("rules.view lookup failed for %d: %s", uid, exc)
                may_pick = False
            published = await db.rules_db.published_rules() if may_pick else None
            if published is not None and published.get("items"):
                markup = rules_btn.picker_btn(published["items"], [], locale)
                text = rules_step.picker_text(published["items"], [], locale)
                if await self._edit_prompt(update, ctx, text, markup):
                    return WAITING_RULES
                return ConversationHandler.END
        return await self._show_proof_prompt(update, ctx, prompt_txt)

    async def _on_reason_unexpected(
        self, update: Update, ctx: ContextTypes.DEFAULT_TYPE
    ) -> int:
        """Reject non-text messages during reason collection."""
        if update.effective_message:
            locale = await locale_for_update(update)
            await reply_rich(
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


# ─────────────────────── Rules picker step ──────────────────────── #


class _RulesStepMixin(_FlowBase):
    """Multi-select rules picker after the reason step."""

    async def _picker_items(self) -> list[dict[str, Any]]:
        published = await db.rules_db.published_rules()
        return published["items"] if published else []

    async def _render_picker(
        self, update: Update, ctx: ContextTypes.DEFAULT_TYPE
    ) -> int:
        scope = flow_scope(ctx, update)
        selected: list[int] = scope.get(self._rules_key, [])
        locale = await locale_for_update(update)
        items = await self._picker_items()
        await self._edit_prompt(
            update,
            ctx,
            rules_step.picker_text(items, selected, locale),
            rules_btn.picker_btn(items, selected, locale),
        )
        return WAITING_RULES

    async def _on_rules_toggle(
        self, update: Update, ctx: ContextTypes.DEFAULT_TYPE
    ) -> int | None:
        q = update.callback_query
        if q is None or q.data is None:
            return WAITING_RULES
        if not self._callback_is_live(update, ctx):
            await self._ignore_stale_callback(update)
            return None
        item_id = rules_step.item_id_from_callback(q.data)
        scope = flow_scope(ctx, update)
        if item_id is not None:
            scope[self._rules_key] = rules_step.toggle(
                scope.get(self._rules_key, []), item_id
            )
        await q.answer()
        return await self._render_picker(update, ctx)

    async def _on_rules_clear(
        self, update: Update, ctx: ContextTypes.DEFAULT_TYPE
    ) -> int | None:
        q = update.callback_query
        if q is None:
            return WAITING_RULES
        if not self._callback_is_live(update, ctx):
            await self._ignore_stale_callback(update)
            return None
        flow_scope(ctx, update)[self._rules_key] = []
        await q.answer()
        return await self._render_picker(update, ctx)

    async def _on_rules_done(
        self, update: Update, ctx: ContextTypes.DEFAULT_TYPE
    ) -> int | None:
        q = update.callback_query
        if q is None:
            return WAITING_RULES
        if not self._callback_is_live(update, ctx):
            await self._ignore_stale_callback(update)
            return None
        scope = flow_scope(ctx, update)
        locale = await locale_for_update(update)
        if not scope.get(self._rules_key) and not scope.get(self._rules_note_key):
            await q.answer(
                t("rules.picker.require_selection", locale, plain=True), show_alert=True
            )
            return WAITING_RULES
        await q.answer()
        prompt_txt = self.proof.step_prompt(
            self._get_target(scope, locale),
            self.action,
            scope.get(self._reason_key, ""),
            scope.get(self._extra_info_key, ""),
            locale,
        )
        return await self._show_proof_prompt(update, ctx, prompt_txt)

    async def _on_rules_other(
        self, update: Update, ctx: ContextTypes.DEFAULT_TYPE
    ) -> int | None:
        q = update.callback_query
        if q is None:
            return WAITING_RULES
        if not self._callback_is_live(update, ctx):
            await self._ignore_stale_callback(update)
            return None
        await q.answer()
        msg = update.effective_message
        if msg is not None:
            await reply_rich(
                msg,
                t("rules.picker.ask_note", await locale_for_update(update), plain=True),
                log_label=f"{self.action} rules-note",
                parse_mode=None,
            )
        return WAITING_RULES_NOTE

    async def _on_rules_note_text(
        self, update: Update, ctx: ContextTypes.DEFAULT_TYPE
    ) -> int:
        msg = update.effective_message
        if msg is None or not msg.text:
            return WAITING_RULES_NOTE
        note = msg.text.strip()
        locale = await locale_for_update(update)
        if not note or len(note) > MAX_RULES_NOTE_LEN:
            await reply_rich(
                msg,
                t(
                    "rules.picker.bad_note",
                    locale,
                    limit=MAX_RULES_NOTE_LEN,
                    plain=True,
                ),
                log_label=f"{self.action} rules-note-limit",
                parse_mode=None,
            )
            return WAITING_RULES_NOTE
        scope = flow_scope(ctx, update)
        scope[self._rules_note_key] = note
        prompt_txt = self.proof.step_prompt(
            self._get_target(scope, locale),
            self.action,
            scope.get(self._reason_key, ""),
            scope.get(self._extra_info_key, ""),
            locale,
        )
        return await self._show_proof_prompt(update, ctx, prompt_txt)


# ─────────────────── ConversationHandler factory ────────────────── #


class _ModActionFlow(_ReasonStepMixin, _RulesStepMixin, _ProofStepMixin, _FlowBase):
    """Per-action ConversationHandler state and callback container."""

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
        # * Every command except this flow's own re-entry must reach its own
        # * handler. A fallback that swallows them loses the moderator's intent
        # * (for example /tcunban during proof collection).
        fallback_filter = ALL_PREFIXES_CMD_FILTER & ~build_conversation_escape_filter(
            *_OWN_COMMANDS.get(self.action, ())
        )
        if escape_filter is not None:
            fallback_filter = fallback_filter & ~escape_filter
        states: dict[Any, list[Any]] = {
            WAITING_REASON: reason_state,
            WAITING_PROOF: proof_state,
        }
        if self.rules_enabled:
            states[WAITING_RULES] = [
                CallbackQueryHandler(
                    self._on_rules_toggle, pattern=r"^rules_step:pick:\d+$"
                ),
                CallbackQueryHandler(self._on_rules_done, pattern=r"^rules_step:done$"),
                CallbackQueryHandler(
                    self._on_rules_other, pattern=r"^rules_step:other$"
                ),
                CallbackQueryHandler(
                    self._on_rules_clear, pattern=r"^rules_step:clear$"
                ),
                CallbackQueryHandler(self._on_cancel, pattern=r"^rules_step:cancel$"),
                CallbackQueryHandler(
                    self._on_cancel, pattern=rf"^{self.action}_cancel$"
                ),
            ]
            states[WAITING_RULES_NOTE] = [
                MessageHandler(
                    filters.TEXT & ~ALL_PREFIXES_CMD_FILTER, self._on_rules_note_text
                ),
                # * The picker's Cancel button stays visible after "Other".
                CallbackQueryHandler(self._on_cancel, pattern=r"^rules_step:cancel$"),
                CallbackQueryHandler(
                    self._on_cancel, pattern=rf"^{self.action}_cancel$"
                ),
            ]
        return ConversationHandler(
            entry_points=[MessageHandler(entry_filter, entry_fn)],
            states=states,
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
    *,
    min_role: RoleName,
    rules_enabled: bool = False,
) -> ConversationHandler:
    """Build a generic reason + rules + proof ConversationHandler."""
    flow = _ModActionFlow(
        reason.action,
        reason,
        proof,
        executor,
        min_role,
        rules_enabled=rules_enabled,
    )
    return flow.build(entry_fn, entry_filter, escape_filter)
