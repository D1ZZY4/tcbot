# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Ban ConversationHandler factory."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from tcbot.modules.helper.handlers import (
    CallbackQueryHandler,
    ConversationHandler,
    MessageHandler,
)
from tcbot.modules.helper.pipelines.ban_confirmation import on_ban_update_continue
from tcbot.modules.helper.pipelines.ban_proof_handlers import (
    on_cancel_proof,
    on_done_proof,
    on_proof_received,
    on_proof_timeout,
    on_proof_unexpected,
)
from tcbot.modules.helper.pipelines.ban_session import (
    WAITING_PROOF,
    WAITING_UPDATE_CONFIRM,
    proof,
)
from tcbot.modules.helper.pipelines.proof_steps import PROOF_MEDIA_FILTER
from tcbot.utils.prefixes import (
    ALL_PREFIXES_CMD_FILTER,
    build_conversation_escape_filter,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from pyrogram.filters import Filter as BaseFilter


def ban_conversation(
    entry_fn: Callable[..., Any],
    entry_filter: BaseFilter,
    *,
    extra_states: dict[Any, list[Any]] | None = None,
) -> ConversationHandler:
    """Return the ban ConversationHandler with the given entry-point function."""
    states: dict[Any, list[Any]] = {
        WAITING_PROOF: [
            CallbackQueryHandler(on_cancel_proof, pattern=rf"^{proof.action}_cancel$"),
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
            CallbackQueryHandler(on_cancel_proof, pattern=rf"^{proof.action}_cancel$"),
        ],
    }
    if extra_states:
        states.update(extra_states)
    return ConversationHandler(
        entry_points=[MessageHandler(entry_filter, entry_fn)],
        states=states,
        fallbacks=[
            # * Only this conversation's own re-entry command may end proof collection.
            # * Swallowing other commands loses the moderator's intent: /tcunban
            # * sent here would cancel the ban and never unban anyone.
            MessageHandler(
                ALL_PREFIXES_CMD_FILTER
                & ~build_conversation_escape_filter("tcban", "tcb"),
                on_proof_timeout,
            ),
            CallbackQueryHandler(on_cancel_proof, pattern=r"^rules_step:cancel$"),
            CallbackQueryHandler(on_cancel_proof, pattern=r"^ban_cancel$"),
        ],
        per_chat=True,
        per_user=True,
        per_message=False,
    )


__all__ = ["ban_conversation"]
