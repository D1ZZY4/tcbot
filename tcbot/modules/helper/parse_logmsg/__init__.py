# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Log-message template builders for moderation, appeals, role changes, and groups."""

from __future__ import annotations

from .appeals import (
    _appeal_decision_edit,
    appeal_approved_edit,
    appeal_received_log,
    appeal_rejected_edit,
    appeal_submitted_log,
    appeal_unban_log,
)
from .core import LogBuilder
from .groups import (
    _MAX_BROADCAST_PREVIEW_LEN,
    broadcast_log,
    group_bot_removed_log,
    group_connected_log,
    group_connection_rejected_log,
    group_disconnected_log,
)
from .moderation import (
    ban_log,
    ban_update_log,
    kick_log,
    mute_log,
    proof_caption_new,
    proof_caption_update,
    resetwarns_log,
    unban_log,
    unmute_log,
    unwarn_log,
    warn_log,
)
from .roles import (
    _role_title,
    demoted,
    ownership_transferred,
    promote_approved_log,
    promote_rejected_log,
    promote_request_log,
    promoted,
)

__all__ = [
    "_MAX_BROADCAST_PREVIEW_LEN",
    "LogBuilder",
    "_appeal_decision_edit",
    "_role_title",
    "appeal_approved_edit",
    "appeal_received_log",
    "appeal_rejected_edit",
    "appeal_submitted_log",
    "appeal_unban_log",
    "ban_log",
    "ban_update_log",
    "broadcast_log",
    "demoted",
    "group_bot_removed_log",
    "group_connected_log",
    "group_connection_rejected_log",
    "group_disconnected_log",
    "kick_log",
    "mute_log",
    "ownership_transferred",
    "promote_approved_log",
    "promote_rejected_log",
    "promote_request_log",
    "promoted",
    "proof_caption_new",
    "proof_caption_update",
    "resetwarns_log",
    "unban_log",
    "unmute_log",
    "unwarn_log",
    "warn_log",
]
