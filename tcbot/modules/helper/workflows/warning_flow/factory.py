# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Warn executor adapter and ConversationHandler factory."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from tcbot.modules.helper.workflows.reason_flow import build_modaction_conv
from tcbot.modules.helper.workflows.warning_flow.issue import execute_warn
from tcbot.modules.helper.workflows.warning_flow.shared import proof, reason
from tcbot.utils.logger import get_logger

if TYPE_CHECKING:
    from collections.abc import Callable

    from telegram import Update
    from telegram.ext import ContextTypes
    from telegram.ext.filters import BaseFilter

log = get_logger(__name__)


async def _exec_warn(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Pop warn data from user_data and call execute_warn."""
    if ctx.user_data is None:
        log.warning("_exec_warn called without user_data")
        return
    target_id = ctx.user_data.pop("warn_target_id", 0)
    target_name = ctx.user_data.pop("warn_target_name", "")
    reason_text = ctx.user_data.pop("warn_reason", "")
    proof_msgs = ctx.user_data.pop("warn_proof_msgs", None)
    ctx.user_data.pop("warn_extra_info", None)
    await execute_warn(
        update,
        ctx,
        target_id,
        target_name,
        reason_text,
        proof_msgs=proof_msgs,
    )


def warn_conversation(
    entry_fn: Callable[..., Any],
    entry_filter: BaseFilter,
    *,
    escape_filter: BaseFilter | None = None,
) -> object:
    """Return the warn ConversationHandler via the central reason_flow factory."""
    return build_modaction_conv(
        reason,
        proof,
        entry_fn,
        _exec_warn,
        entry_filter,
        escape_filter=escape_filter,
        min_role="tester",
    )
