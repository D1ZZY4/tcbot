# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Community ban helpers over the moderation decision tables.

A ban is one decision in ``moderation_actions``. The investigation lives
in ``moderation_cases``, the archived proof in
``moderation_evidence_uploads`` and ``moderation_evidence_items``, the
Telegram messages beside it in ``moderation_messages``, and the appeal
against it in ``moderation_appeals``.
"""

from __future__ import annotations

from ._compose import compose_row, compose_rows
from ._queries import (
    action_by_ref,
    active_ban_count,
    active_ban_user_ids,
    active_bans_for_users,
    active_bans_page,
    get_active_ban,
    get_ban,
    user_appeal_count,
    user_appealable_bans,
    user_ban_count,
    user_bans,
)
from ._shared import CONSTRAINT_ACTIVE_USER, CONSTRAINT_EXTERNAL_REF
from ._writes import (
    accept_appeal,
    claim_appeal_decision,
    clear_review,
    create_ban,
    deactivate_all_active_bans,
    deactivate_extra_active_bans,
    make_ban_id,
    release_stale_review,
    restore_review,
    set_appeal_log_msg,
    set_log_message_id,
    set_rejected_by,
    set_review_if_absent,
    submit_appeal,
    update_ban,
)

__all__ = [
    "CONSTRAINT_ACTIVE_USER",
    "CONSTRAINT_EXTERNAL_REF",
    "accept_appeal",
    "action_by_ref",
    "active_ban_count",
    "active_ban_user_ids",
    "active_bans_for_users",
    "active_bans_page",
    "claim_appeal_decision",
    "clear_review",
    "compose_row",
    "compose_rows",
    "create_ban",
    "deactivate_all_active_bans",
    "deactivate_extra_active_bans",
    "get_active_ban",
    "get_ban",
    "make_ban_id",
    "release_stale_review",
    "restore_review",
    "set_appeal_log_msg",
    "set_log_message_id",
    "set_rejected_by",
    "set_review_if_absent",
    "submit_appeal",
    "update_ban",
    "user_appeal_count",
    "user_appealable_bans",
    "user_ban_count",
    "user_bans",
]
