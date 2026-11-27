# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Kick conversation factory: reason, proof, and the mod-action flow."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from tcbot.modules.helper.pipelines.kick_executor import _exec_kick
from tcbot.modules.helper.pipelines.mod_action_steps import (
    BuildReason,
    build_modaction_conv,
)
from tcbot.modules.helper.pipelines.proof_steps import BuildProof

if TYPE_CHECKING:
    from collections.abc import Callable

    from pyrogram.filters import Filter as BaseFilter


# * Per-action BuildReason and BuildProof instances; imported by kick.py
reason = BuildReason("kick", skip_allowed=False)
proof = BuildProof("kick")


def kick_conversation(entry_fn: Callable[..., Any], entry_filter: BaseFilter) -> object:
    """Return the kick ConversationHandler via the central mod_action_steps factory."""
    return build_modaction_conv(
        reason,
        proof,
        entry_fn,
        _exec_kick,
        entry_filter,
        min_role="moderator",
    )


__all__ = ["kick_conversation", "proof", "reason"]
