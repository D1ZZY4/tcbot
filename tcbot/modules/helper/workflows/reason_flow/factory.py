# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Generic reason-plus-proof ConversationHandler factory."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from telegram.ext import ConversationHandler
from telegram.ext.filters import BaseFilter

from tcbot.modules.helper.workflows.proof_flow import BuildProof
from tcbot.modules.helper.workflows.reason_flow.base import (
    WAITING_PROOF,
    WAITING_REASON,
)
from tcbot.modules.helper.workflows.reason_flow.builder import BuildReason
from tcbot.modules.helper.workflows.reason_flow.flow import _ModActionFlow

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = ["WAITING_PROOF", "WAITING_REASON", "build_modaction_conv"]


# ─────────────── Generic ConversationHandler factory ────────────── #


def build_modaction_conv(
    reason: BuildReason,
    proof: BuildProof,
    entry_fn: Callable[..., Any],
    executor: Callable[..., Any],
    entry_filter: BaseFilter,
    escape_filter: BaseFilter | None = None,
    *,
    min_role: str,
) -> ConversationHandler:
    """Build a generic reason + proof ConversationHandler.

    ``min_role`` names the lowest rank that may still enforce at Done/Skip
    time; the entry decorator owns the same value, and Done/Skip taps
    re-check it so a mid-window demotion cannot enforce.
    """
    return _ModActionFlow(reason.action, reason, proof, executor, min_role).build(
        entry_fn, entry_filter, escape_filter
    )
