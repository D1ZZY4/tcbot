# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Central reason-step infrastructure."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from pyrogram import ContinuePropagation, filters
from pyrogram.filters import Filter as BaseFilter
from pyrogram.types import InlineKeyboardMarkup

from tcbot.modules.helper import guards
from tcbot.modules.helper.buttons import reason_step_btn
from tcbot.modules.helper.context import Ctx
from tcbot.modules.helper.extraction import parse_user_id_token
from tcbot.modules.helper.handlers import (
    CallbackQueryHandler,
    ConversationHandler,
    MessageHandler,
)
from tcbot.modules.helper.locale import locale_for_update
from tcbot.modules.helper.messages import (
    replies,
    reply_rich,
    reply_rich_result,
    safe_edit_cb,
    safe_edit_message,
)
from tcbot.modules.helper.pipelines.proof_steps import PROOF_MEDIA_FILTER, BuildProof
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


# ───────────────────────── Reason parsing ───────────────────────── #


WAITING_REASON = 0
WAITING_PROOF = 1

MAX_REASON_LEN: int = 1000

# * Re-entry commands of each moderation conversation. They stay in the fallback so
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


# ──────────────────────── Shared conversation state ─────────────────────── #


class _FlowBase:
    """Shared conversation state plus cancel and fallback handlers."""

    def __init__(
        self,
        action: str,
        reason: BuildReason,
        proof: BuildProof,
        executor: Callable[..., Any],
        min_role: RoleName,
    ) -> None:
        self.action = action
        self.reason = reason
        self.proof = proof
        self.executor = executor
        self.min_role: RoleName = min_role
        self._reason_key = f"{action}_reason"
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
        ctx: Ctx,
        text: str,
        markup: InlineKeyboardMarkup,
    ) -> bool:
        """Edit the shared prompt message, replying when it cannot be edited."""
        scope = flow_scope(ctx)
        chat_id = scope.get(self._prompt_chat_key)
        message_id = scope.get(self._prompt_id_key)
        try:
            if chat_id is not None and message_id is not None:
                await safe_edit_message(
                    ctx.bot, chat_id, message_id, text, reply_markup=markup
                )
            else:
                msg = ctx.effective_message
                if msg is None:
                    return False
                await reply_rich_result(msg, text, reply_markup=markup)
            return True
        except Exception as exc:
            log.debug("%s prompt edit failed: %s", self.action, exc)
            return False

    async def _show_proof_prompt(self, ctx: Ctx, prompt_txt: str) -> int:
        """Render the proof prompt and enter the proof state."""
        locale = await locale_for_update(ctx)
        if not await self._edit_prompt(ctx, prompt_txt, self.proof.keyboard(locale)):
            self._clear_scope(ctx)
            return ConversationHandler.END
        return WAITING_PROOF

    def _callback_is_live(self, ctx: Ctx) -> bool:
        """Reject a tap on a button left behind by an earlier conversation."""
        return callback_is_current(
            ctx,
            flow_scope(ctx),
            chat_key=self._prompt_chat_key,
            message_key=self._prompt_id_key,
        )

    async def _ignore_stale_callback(self, ctx: Ctx) -> None:
        """Release a stale tap to another flow that may own the callback."""
        raise ContinuePropagation()

    def _clear_scope(self, ctx: Ctx) -> None:
        """Remove all action keys from the conversation scope.

        Only this action's keys go: another conversation may hold its own payload
        in the same conversation scope.
        """
        scope = flow_scope(ctx)
        prefix = f"{self.action}_"
        clear_flow_scope(ctx, keys=[k for k in scope if k.startswith(prefix)])

    async def _recheck_tapper(self, ctx: Ctx) -> bool:
        """Re-verify the tapper still meets min_role."""
        q = ctx.callback_query
        tap_user = ctx.effective_user
        tap_msg = ctx.effective_message
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
        self._clear_scope(ctx)
        return False

    async def _on_cancel(self, ctx: Ctx) -> int | None:
        q = ctx.callback_query
        if q is None:
            return ConversationHandler.END
        if not self._callback_is_live(ctx):
            await self._ignore_stale_callback(ctx)
            return None
        self._clear_scope(ctx)
        locale = await locale_for_update(ctx)
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

    async def _on_end_conv(self, ctx: Ctx) -> int:
        self._clear_scope(ctx)
        if ctx.effective_message:
            locale = await locale_for_update(ctx)
            await reply_rich(
                ctx.effective_message,
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

    async def _on_proof(self, ctx: Ctx) -> int:
        msg = ctx.effective_message
        if msg is None or ctx.user_data is None:
            return WAITING_PROOF
        scope = flow_scope(ctx)
        if scope.get(self._exec_key):
            return ConversationHandler.END
        if msg.photo or msg.video or msg.animation or msg.document:
            existing: list = scope.get(self._proof_msgs_key, [])
            scope[self._proof_msgs_key] = [*existing, msg]
        return WAITING_PROOF

    async def _on_done_proof(self, ctx: Ctx) -> int | None:
        """Execute with everything collected once the moderator taps Done."""
        q = ctx.callback_query
        if q is None or ctx.user_data is None:
            return ConversationHandler.END
        if not self._callback_is_live(ctx):
            await self._ignore_stale_callback(ctx)
            return None
        scope = flow_scope(ctx)
        locale = await locale_for_update(ctx)
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
        if not await self._recheck_tapper(ctx):
            scope.pop(self._exec_key, None)
            return ConversationHandler.END
        try:
            await q.answer()
        except Exception as exc:
            log.debug("%s done-proof q.answer failed: %s", self.action, exc)
        try:
            await self.executor(ctx)
        except BaseException:
            self._clear_scope(ctx)
            raise
        self._clear_scope(ctx)
        return ConversationHandler.END

    async def _on_skip_proof(self, ctx: Ctx) -> int | None:
        q = ctx.callback_query
        if q is None or ctx.user_data is None:
            return WAITING_PROOF
        if not self._callback_is_live(ctx):
            await self._ignore_stale_callback(ctx)
            return None
        scope = flow_scope(ctx)
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
        if not await self._recheck_tapper(ctx):
            scope.pop(self._exec_key, None)
            return ConversationHandler.END
        qa_result, exec_result = await asyncio.gather(
            q.answer(),
            self.executor(ctx),
            return_exceptions=True,
        )
        throw_if_cancelled((qa_result, exec_result))
        if isinstance(qa_result, BaseException):
            log.debug("%s skip-proof q.answer failed: %s", self.action, qa_result)
        if isinstance(exec_result, BaseException):
            self._clear_scope(ctx)
            raise exec_result
        self._clear_scope(ctx)
        return ConversationHandler.END

    async def _on_proof_unexpected(self, ctx: Ctx) -> int:
        """Reject unexpected message types during proof collection."""
        if not flow_scope(ctx).get(f"{self.action}_target_id"):
            # * All state handlers are registered flat, so this catch-all must
            # * not consume a message that belongs to another active flow.
            raise ContinuePropagation()
        if ctx.effective_message:
            locale = await locale_for_update(ctx)
            await reply_rich(
                ctx.effective_message,
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

    async def _on_reason_text(self, ctx: Ctx) -> int:
        msg = ctx.effective_message
        if msg is None or msg.text is None:
            return WAITING_REASON
        if ctx.user_data is None:
            return WAITING_REASON
        scope = flow_scope(ctx)
        if not scope.get(f"{self.action}_target_id"):
            # * This state handler is registered with every other handler.
            # * Without an active flow it must let another module's text
            # * handler see the update instead of capturing a reason.
            raise ContinuePropagation()
        if not await self._recheck_tapper(ctx):
            return ConversationHandler.END
        text = msg.text.strip()
        locale = await locale_for_update(ctx)
        if not text:
            # * filters.text accepts whitespace-only messages, and the
            # * database rejects a blank reason. Keep the conversation open instead
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
        return await self._after_reason(ctx, prompt_txt)

    async def _on_skip_reason(self, ctx: Ctx) -> int | None:
        q = ctx.callback_query
        if q is None or ctx.user_data is None:
            return WAITING_REASON
        if not self._callback_is_live(ctx):
            await self._ignore_stale_callback(ctx)
            return None
        if not await self._recheck_tapper(ctx):
            return ConversationHandler.END
        scope = flow_scope(ctx)
        locale = await locale_for_update(ctx)
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
            self._clear_scope(ctx)
            return ConversationHandler.END
        return await self._after_reason(ctx, prompt_txt)

    async def _after_reason(self, ctx: Ctx, prompt_txt: str) -> int:
        """Move from the reason step straight to proof collection."""
        return await self._show_proof_prompt(ctx, prompt_txt)

    async def _on_reason_unexpected(self, ctx: Ctx) -> int:
        """Reject non-text messages during reason collection."""
        if not flow_scope(ctx).get(f"{self.action}_target_id"):
            raise ContinuePropagation()
        if ctx.effective_message:
            locale = await locale_for_update(ctx)
            await reply_rich(
                ctx.effective_message,
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


# ─────────────────── ConversationHandler factory ────────────────── #


class _ModActionFlow(_ReasonStepMixin, _ProofStepMixin, _FlowBase):
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
                filters.text & ~ALL_PREFIXES_CMD_FILTER, self._on_reason_text
            ),
            CallbackQueryHandler(self._on_cancel, pattern=rf"^{self.action}_cancel$"),
            MessageHandler(
                ~filters.text & ~ALL_PREFIXES_CMD_FILTER,
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
        # * Every command except this conversation's own re-entry must reach its own
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
) -> ConversationHandler:
    """Build a generic reason + proof ConversationHandler."""
    flow = _ModActionFlow(reason.action, reason, proof, executor, min_role)
    return flow.build(entry_fn, entry_filter, escape_filter)
