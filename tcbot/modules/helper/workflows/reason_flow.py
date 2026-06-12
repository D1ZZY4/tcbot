# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Studio

"""Central reason-step infrastructure."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackQueryHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    TypeHandler,
    filters,
)

from tcbot import cfg
from tcbot.modules.helper import replies
from tcbot.modules.helper.workflows.proof_flow import BuildProof
from tcbot.utils.prefixes import ALL_PREFIXES_CMD_FILTER

if TYPE_CHECKING:
    from collections.abc import Callable

    from telegram.ext.filters import BaseFilter

log = logging.getLogger(__name__)

# * State constants used by all moderation ConversationHandlers
WAITING_REASON = 0
WAITING_PROOF = 1


# ───────────────────────── Reason parsing ───────────────────────── #


def parse_inline_reason(
    args: list[str],
    *,
    has_explicit_target: bool,
) -> str:
    """Extract any inline reason text from command arguments."""
    tokens = args[1:] if has_explicit_target else args
    return " ".join(tokens).strip()


# ─────────────────────────── BuildReason ────────────────────────── #


@dataclass(frozen=True)
class BuildReason:
    """Configurable reason-step keyboard and prompt builder."""

    action: str
    skip_allowed: bool = field(default=True, kw_only=True)
    skip_label: str = field(default="Skip", kw_only=True)
    cancel_label: str = field(default="Cancel", kw_only=True)

    def keyboard(self) -> InlineKeyboardMarkup:
        """Reason-step keyboard. Includes Skip only when skip_allowed is True."""
        buttons: list[InlineKeyboardButton] = []
        if self.skip_allowed:
            buttons.append(
                InlineKeyboardButton(
                    self.skip_label, callback_data=f"{self.action}_skip_reason"
                )
            )
        buttons.append(
            InlineKeyboardButton(
                self.cancel_label, callback_data=f"{self.action}_cancel"
            )
        )
        return InlineKeyboardMarkup([buttons])

    def prompt(
        self,
        target_mention: str,
        action_label: str,
        extra_info: str = "",
    ) -> str:
        """Prompt asking the moderator to type a reason."""
        suffix = f" {extra_info}" if extra_info else ""
        skip_hint = f", or tap <b>{self.skip_label}</b>" if self.skip_allowed else ""
        return (
            f"About to {action_label} {target_mention}{suffix}.\n"
            f"What's the reason? Type it below{skip_hint}."
        )


# ─────────────── Generic ConversationHandler factory ────────────── #


def build_modaction_conv(
    reason: BuildReason,
    proof: BuildProof,
    entry_fn: Callable[..., Any],
    executor: Callable[..., Any],
    entry_filter: BaseFilter,
    escape_filter: BaseFilter | None = None,
) -> ConversationHandler:
    """Build a generic reason + proof ConversationHandler."""
    action = reason.action
    _reason_key = f"{action}_reason"
    _proof_key = f"{action}_proof_desc"
    _extra_info_key = f"{action}_extra_info"
    _prompt_chat_key = f"{action}_prompt_chat"
    _prompt_id_key = f"{action}_prompt_id"

    def _get_target(ctx: ContextTypes.DEFAULT_TYPE) -> str:
        return (
            ctx.user_data.get(f"{action}_target_name")
            or ctx.user_data.get(f"{action}_target_fname")
            or "target"
        )

    # ── WAITING_REASON handlers ──────────────────────────────────── #

    async def _on_reason_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
        text = update.effective_message.text.strip()
        ctx.user_data[_reason_key] = text
        extra_info = ctx.user_data.get(_extra_info_key, "")
        prompt_txt = proof.step_prompt(_get_target(ctx), action, text, extra_info)
        prompt_chat = ctx.user_data.get(_prompt_chat_key)
        prompt_id = ctx.user_data.get(_prompt_id_key)
        if prompt_id and prompt_chat:
            try:
                await ctx.bot.edit_message_text(
                    prompt_txt,
                    chat_id=prompt_chat,
                    message_id=prompt_id,
                    parse_mode="HTML",
                    reply_markup=proof.keyboard(),
                )
            except Exception:
                log.exception("%s prompt edit failed (reason step)", action)
        else:
            await update.effective_message.reply_text(
                prompt_txt,
                parse_mode="HTML",
                reply_markup=proof.keyboard(),
            )
        return WAITING_PROOF

    async def _on_skip_reason(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
        q = update.callback_query
        ctx.user_data[_reason_key] = replies.NO_REASON
        extra_info = ctx.user_data.get(_extra_info_key, "")
        prompt_txt = proof.step_prompt(
            _get_target(ctx), action, replies.NO_REASON, extra_info
        )
        try:
            await asyncio.gather(
                q.answer(),
                q.edit_message_text(
                    prompt_txt, parse_mode="HTML", reply_markup=proof.keyboard()
                ),
            )
        except Exception:
            log.exception("%s prompt edit failed (skip-reason step)", action)
        return WAITING_PROOF

    # ── WAITING_PROOF handlers ───────────────────────────────────── #

    async def _on_proof(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
        p = proof.record(update.effective_message)
        if p:
            ctx.user_data[_proof_key] = p
        await executor(update, ctx)
        return ConversationHandler.END

    async def _on_skip_proof(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
        await asyncio.gather(
            update.callback_query.answer(),
            executor(update, ctx),
            return_exceptions=True,
        )
        return ConversationHandler.END

    # ── Cancel / fallback ────────────────────────────────────────── #

    async def _on_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
        q = update.callback_query
        await asyncio.gather(
            q.answer(),
            q.edit_message_text(f"Got it, {action} cancelled. No action was taken."),
            return_exceptions=True,
        )
        return ConversationHandler.END

    async def _end_conv(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
        await update.effective_message.reply_text(
            f"{action.capitalize()} operation cancelled."
        )
        return ConversationHandler.END

    async def _on_timeout(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
        if update.effective_message:
            await update.effective_message.reply_text(
                f"{action.capitalize()} operation timed out. No action was taken."
            )
        return ConversationHandler.END

    # ── Build states ─────────────────────────────────────────────── #

    reason_state: list = [
        MessageHandler(filters.TEXT & ~ALL_PREFIXES_CMD_FILTER, _on_reason_text),
        CallbackQueryHandler(_on_cancel, pattern=rf"^{action}_cancel$"),
    ]
    if reason.skip_allowed:
        reason_state.insert(
            1,
            CallbackQueryHandler(
                _on_skip_reason,
                pattern=rf"^{action}_skip_reason$",
            ),
        )

    proof_state = [
        MessageHandler(filters.PHOTO | filters.VIDEO, _on_proof),
        CallbackQueryHandler(_on_skip_proof, pattern=rf"^{action}_skip_proof$"),
        CallbackQueryHandler(_on_cancel, pattern=rf"^{action}_cancel$"),
    ]

    fallback_filter = ALL_PREFIXES_CMD_FILTER
    if escape_filter is not None:
        fallback_filter = fallback_filter & ~escape_filter

    return ConversationHandler(
        entry_points=[MessageHandler(entry_filter, entry_fn)],
        states={
            WAITING_REASON: reason_state,
            WAITING_PROOF: proof_state,
            ConversationHandler.TIMEOUT: [TypeHandler(Update, _on_timeout)],
        },
        fallbacks=[
            CallbackQueryHandler(_on_cancel, pattern=rf"^{action}_cancel$"),
            MessageHandler(fallback_filter, _end_conv),
        ],
        per_user=True,
        per_chat=True,
        conversation_timeout=cfg.proof_timeout,
        per_message=False,
    )
