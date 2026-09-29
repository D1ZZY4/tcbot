# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""WAITING_REASON handlers for mod-action flows."""

from __future__ import annotations

import asyncio

from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler

from tcbot.modules.helper import replies
from tcbot.modules.helper.locale import locale_for_update
from tcbot.modules.helper.parse_editmsg import safe_reply
from tcbot.modules.helper.workflows.reason_flow.base import (
    WAITING_PROOF,
    WAITING_REASON,
    _FlowBase,
)
from tcbot.modules.helper.workflows.reason_flow.parsing import (
    is_reason_too_long,
    reason_too_long_text,
)
from tcbot.utils.dispatch import throw_if_cancelled
from tcbot.utils.i18n import t
from tcbot.utils.logger import get_logger

log = get_logger(__name__)


class _ReasonStepMixin(_FlowBase):
    """Reason-text, skip-reason, and unexpected-message handlers.

    Mixed into :class:`_ModActionFlow` over :class:`_FlowBase`; never
    instantiated on its own.
    """

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
        throw_if_cancelled(results)
        if isinstance(results[1], BaseException):
            log.debug(
                "%s prompt edit failed (skip-reason step): %s", self.action, results[1]
            )
            # * Proof prompt is invisible; clear state to avoid locking
            # * them in WAITING_PROOF with no visible UI element to interact with.
            self._clear_user_data(ctx)
            return ConversationHandler.END
        return WAITING_PROOF

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
