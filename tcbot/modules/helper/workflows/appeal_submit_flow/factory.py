# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""ConversationHandler factory for the appeal submission flow."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from telegram.ext import (
    CallbackQueryHandler,
    ConversationHandler,
    MessageHandler,
    filters,
)

from tcbot.modules.helper.workflows.appeal_submit_flow.gates import WAITING_APPEAL
from tcbot.utils.prefixes import ALL_PREFIXES_CMD_FILTER

if TYPE_CHECKING:
    from collections.abc import Callable

    from telegram.ext.filters import BaseFilter


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
    """Assemble the appeal ConversationHandler from bound step methods.

    Note: ``conversation_timeout`` is intentionally absent.  PTB's timeout
    support requires the ``job-queue`` extra (APScheduler 3.x backend) which
    is already used by this project's persistent MongoDBJobStore setup.
    Stale sessions are detected via the 72-hour ``_STALE_REVIEW_WINDOW`` guard
    in ``_start`` and ended via the ``_end`` fallback (triggered on any command)
    or Cancel.
    """
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
            # * A fresh deep link restarts the flow instead of falling
            # * into the generic session-ended handler below.
            MessageHandler(entry_filter, on_entry),
            MessageHandler(ALL_PREFIXES_CMD_FILTER, on_end),
        ],
        per_chat=True,
        per_user=True,
        per_message=False,
    )
