# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Ban ConversationHandler factory."""

from __future__ import annotations

from typing import TYPE_CHECKING

from telegram.ext import CallbackQueryHandler, ConversationHandler, MessageHandler

from tcbot.modules.helper.workflows.ban_flow.handlers import (
    on_ban_update_continue,
    on_cancel_proof,
    on_done_proof,
    on_proof_received,
    on_proof_timeout,
    on_proof_unexpected,
)
from tcbot.modules.helper.workflows.ban_flow.shared import (
    WAITING_PROOF,
    WAITING_UPDATE_CONFIRM,
    proof,
)
from tcbot.modules.helper.workflows.proof_flow import PROOF_MEDIA_FILTER
from tcbot.utils.prefixes import ALL_PREFIXES_CMD_FILTER

if TYPE_CHECKING:
    from collections.abc import Callable
    from typing import Any

    from telegram.ext.filters import BaseFilter


def ban_conversation(
    entry_fn: Callable[..., Any], entry_filter: BaseFilter
) -> ConversationHandler:
    """Return the ban ConversationHandler with the given entry-point function.

    Note: ``conversation_timeout`` is intentionally omitted.  PTB's timeout
    support requires the ``job-queue`` extra (APScheduler 3.x backend) which
    conflicts with this project's persistent MongoDBJobStore setup.  Conversations
    are ended via the fallback ``on_proof_timeout`` handler (triggered on any
    command) or by the user pressing Cancel.
    """
    return ConversationHandler(
        entry_points=[MessageHandler(entry_filter, entry_fn)],
        states={
            WAITING_PROOF: [
                CallbackQueryHandler(
                    on_cancel_proof, pattern=rf"^{proof.action}_cancel$"
                ),
                CallbackQueryHandler(
                    on_done_proof, pattern=rf"^{proof.action}_done_proof$"
                ),
                MessageHandler(PROOF_MEDIA_FILTER, on_proof_received),
                MessageHandler(
                    ~PROOF_MEDIA_FILTER & ~ALL_PREFIXES_CMD_FILTER,
                    on_proof_unexpected,
                ),
            ],
            WAITING_UPDATE_CONFIRM: [
                CallbackQueryHandler(on_ban_update_continue, pattern=r"^ban_continue$"),
                CallbackQueryHandler(
                    on_cancel_proof, pattern=rf"^{proof.action}_cancel$"
                ),
            ],
        },
        fallbacks=[MessageHandler(ALL_PREFIXES_CMD_FILTER, on_proof_timeout)],
        per_chat=True,
        per_user=True,
        per_message=False,
    )
