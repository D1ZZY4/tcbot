# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Shared flow state, rank re-check, and cancel paths for mod-action flows."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler

from tcbot.modules.helper import decorators
from tcbot.modules.helper.locale import locale_for_update
from tcbot.modules.helper.parse_editmsg import safe_reply
from tcbot.modules.helper.workflows.proof_flow import BuildProof
from tcbot.utils.dispatch import throw_if_cancelled
from tcbot.utils.formatter import esc, user_ref
from tcbot.utils.i18n import t
from tcbot.utils.logger import get_logger

if TYPE_CHECKING:
    from collections.abc import Callable

    from tcbot.modules.helper.workflows.reason_flow.builder import BuildReason

log = get_logger(__name__)

# * State constants used by all moderation ConversationHandlers
WAITING_REASON = 0
WAITING_PROOF = 1


class _FlowBase:
    """Shared conversation state plus cancel and fallback handlers.

    Mixed with the reason-step and proof-step mixins into
    :class:`_ModActionFlow`; never instantiated on its own.
    """

    def __init__(
        self,
        action: str,
        reason: BuildReason,
        proof: BuildProof,
        executor: Callable[..., Any],
        min_role: str,
    ) -> None:
        self.action = action
        self.reason = reason
        self.proof = proof
        self.executor = executor
        self.min_role = min_role
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
            return user_ref(tid, raw)
        return esc(raw)

    def _clear_user_data(self, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        """Remove all ``{action}_*`` keys from user_data on cancel / timeout."""
        if ctx.user_data is None:
            return
        prefix = f"{self.action}_"
        for key in [k for k in ctx.user_data if k.startswith(prefix)]:
            ctx.user_data.pop(key, None)

    async def _recheck_tapper(
        self, update: Update, ctx: ContextTypes.DEFAULT_TYPE
    ) -> bool:
        """Re-verify the tapper still meets ``min_role`` (no spinner answer).

        Done/Skip taps can land long after the entry command passed its
        decorator; a moderator demoted mid-window must not enforce. The
        success path leaves the spinner for the caller's own answer; on
        failure the query is answered here, flow state is cleared, and
        False is returned (the helper already replied on the prompt).
        """
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
        if await decorators.recheck_executor_rank(
            tap_msg, tap_user.id, min_role=self.min_role
        ):
            return True
        if q is not None:
            try:
                await q.answer()
            except Exception as exc:
                log.debug("%s recheck q.answer failed: %s", self.action, exc)
        self._clear_user_data(ctx)
        return False

    # ── Cancel / fallback ────────────────────────────────────────── #

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
        throw_if_cancelled(results)
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
