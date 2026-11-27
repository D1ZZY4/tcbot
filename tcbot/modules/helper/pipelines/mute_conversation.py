# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Mute conversation factory: reason, proof, and the mod-action flow."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from tcbot.modules.helper.pipelines.mod_action_steps import (
    BuildReason,
    build_modaction_conv,
)
from tcbot.modules.helper.pipelines.mute_executor import _exec_mute
from tcbot.modules.helper.pipelines.proof_steps import BuildProof

if TYPE_CHECKING:
    from collections.abc import Callable

    from pyrogram.filters import Filter as BaseFilter


reason = BuildReason("mute", skip_allowed=False)
proof = BuildProof("mute")


def mute_conversation(
    entry_fn: Callable[..., Any],
    entry_filter: BaseFilter,
    *,
    escape_filter: BaseFilter | None = None,
) -> object:
    """Return the mute ConversationHandler via the central mod_action_steps factory."""
    return build_modaction_conv(
        reason,
        proof,
        entry_fn,
        _exec_mute,
        entry_filter,
        escape_filter=escape_filter,
        min_role="moderator",
    )


__all__ = ["mute_conversation", "proof", "reason"]
