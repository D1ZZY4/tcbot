# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Per-action ConversationHandler state assembled from step mixins."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from telegram.ext import (
    CallbackQueryHandler,
    ConversationHandler,
    MessageHandler,
    filters,
)
from telegram.ext.filters import BaseFilter

from tcbot.modules.helper.workflows.proof_flow import PROOF_MEDIA_FILTER
from tcbot.modules.helper.workflows.reason_flow.base import (
    WAITING_PROOF,
    WAITING_REASON,
    _FlowBase,
)
from tcbot.modules.helper.workflows.reason_flow.proof_step import _ProofStepMixin
from tcbot.modules.helper.workflows.reason_flow.reason_step import _ReasonStepMixin
from tcbot.utils.prefixes import ALL_PREFIXES_CMD_FILTER

if TYPE_CHECKING:
    from collections.abc import Callable


class _ModActionFlow(_ReasonStepMixin, _ProofStepMixin, _FlowBase):
    """Per-action ConversationHandler state and callback container.

    Replaces the previous closure-heavy ``build_modaction_conv`` body so that
    each handler is a named method on an explicit state object.  This keeps the
    public factory function under 10 lines and makes individual handlers
    testable without reproducing the full closure environment.
    """

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
