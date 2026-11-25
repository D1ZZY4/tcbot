# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Warn conversation factory: reason, proof, and the mod-action flow."""

from __future__ import annotations

from typing import TYPE_CHECKING

from tcbot.modules.helper.pipelines.mod_action_steps import (
    BuildReason,
    build_modaction_conv,
)
from tcbot.modules.helper.pipelines.proof_steps import BuildProof
from tcbot.modules.helper.pipelines.warn_executor import _exec_warn

if TYPE_CHECKING:
    from collections.abc import Callable

    from pyrogram.filters import Filter as BaseFilter


reason = BuildReason("warn", skip_allowed=False)
proof = BuildProof("warn")


def warn_conversation(
    entry_fn: Callable[..., object],
    entry_filter: BaseFilter,
    *,
    escape_filter: BaseFilter | None = None,
) -> object:
    """Return the warn ConversationHandler via the central mod_action_steps factory."""
    return build_modaction_conv(
        reason,
        proof,
        entry_fn,
        _exec_warn,
        entry_filter,
        escape_filter=escape_filter,
        min_role="moderator",
        rules_enabled=True,
    )


__all__ = ["proof", "reason", "warn_conversation"]
