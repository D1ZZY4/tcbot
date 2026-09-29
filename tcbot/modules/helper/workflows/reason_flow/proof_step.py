# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""WAITING_PROOF handlers for mod-action flows."""

from __future__ import annotations

import asyncio

from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler

from tcbot.modules.helper.locale import locale_for_update
from tcbot.modules.helper.parse_editmsg import safe_reply
from tcbot.modules.helper.workflows.reason_flow.base import (
    WAITING_PROOF,
    _FlowBase,
)
from tcbot.utils.dispatch import throw_if_cancelled
from tcbot.utils.i18n import t
from tcbot.utils.logger import get_logger

log = get_logger(__name__)


class _ProofStepMixin(_FlowBase):
    """Proof-buffer, Done/Skip execution, and unexpected-message handlers.

    Mixed into :class:`_ModActionFlow` over :class:`_FlowBase`; never
    instantiated on its own.
    """

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
        # * Rank re-check: a moderator demoted after the entry command
        # * passed its decorator must not enforce from a stale prompt.
        if not await self._recheck_tapper(update, ctx):
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
        # * Rank re-check first: the executor below must not run for a
        # * tapper who lost the rank since the entry command.
        if not await self._recheck_tapper(update, ctx):
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
        throw_if_cancelled((qa_result, exec_result))
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
