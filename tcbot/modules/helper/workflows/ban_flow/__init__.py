# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Ban executor + proof collection conversation."""

from __future__ import annotations

import asyncio

from telegram.ext import ConversationHandler

from tcbot import database as db
from tcbot.modules.helper.locale import locale_for_user
from tcbot.modules.helper.workflows.ban_flow.executor import _execute_ban
from tcbot.modules.helper.workflows.ban_flow.factory import ban_conversation
from tcbot.modules.helper.workflows.ban_flow.handlers import (
    demote_ban_target,
    on_ban_update_continue,
    on_cancel_proof,
    on_done_proof,
    on_proof_received,
    on_proof_timeout,
    on_proof_unexpected,
    proof_prompt_content,
)
from tcbot.modules.helper.workflows.ban_flow.persist import (
    _execute_ban_update,
    _execute_new_ban,
)
from tcbot.modules.helper.workflows.ban_flow.session import (
    _cancel_proof_session,
    _clear_ban_state,
    _flush_session,
    _proof_sessions,
    _ProofSession,
)
from tcbot.modules.helper.workflows.ban_flow.shared import (
    _PROOF_COLLECT_MAX_S,
    BAN_USER_DATA_KEYS,
    WAITING_PROOF,
    WAITING_UPDATE_CONFIRM,
    log,
    proof,
)

__all__ = [
    "BAN_USER_DATA_KEYS",
    "WAITING_PROOF",
    "WAITING_UPDATE_CONFIRM",
    "_PROOF_COLLECT_MAX_S",
    "ConversationHandler",
    "_ProofSession",
    "_cancel_proof_session",
    "_clear_ban_state",
    "_execute_ban",
    "_execute_ban_update",
    "_execute_new_ban",
    "_flush_session",
    "_proof_sessions",
    "asyncio",
    "ban_conversation",
    "db",
    "demote_ban_target",
    "locale_for_user",
    "log",
    "on_ban_update_continue",
    "on_cancel_proof",
    "on_done_proof",
    "on_proof_received",
    "on_proof_timeout",
    "on_proof_unexpected",
    "proof",
    "proof_prompt_content",
]
