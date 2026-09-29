# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Mute executor adapter and ConversationHandler factory."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from tcbot.modules.helper.workflows.muting_flow.mute import _execute_mute
from tcbot.modules.helper.workflows.muting_flow.shared import proof, reason
from tcbot.modules.helper.workflows.reason_flow import build_modaction_conv
from tcbot.utils.logger import get_logger

if TYPE_CHECKING:
    from collections.abc import Callable

    from telegram import Update
    from telegram.ext import ContextTypes
    from telegram.ext.filters import BaseFilter

log = get_logger(__name__)


async def _exec_mute(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Copy mute data from user_data, clean up, then call _execute_mute."""
    meta: dict[str, Any] = {}
    if ctx.user_data is not None:
        meta = {k: v for k, v in ctx.user_data.items() if k.startswith("mute_")}
        for k in list(meta):
            ctx.user_data.pop(k, None)
    await _execute_mute(ctx.bot, update, meta)


def mute_conversation(
    entry_fn: Callable[..., Any],
    entry_filter: BaseFilter,
    *,
    escape_filter: BaseFilter | None = None,
) -> object:
    """Return the mute ConversationHandler via the central reason_flow factory."""
    return build_modaction_conv(
        reason,
        proof,
        entry_fn,
        _exec_mute,
        entry_filter,
        escape_filter=escape_filter,
        min_role="tester",
    )
