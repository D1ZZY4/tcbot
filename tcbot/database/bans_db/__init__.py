# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Bans collection helpers - manages all ban-related database operations."""

from __future__ import annotations

from .queries import (
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
from .records import (
    _bans,
    clear_review,
    create_ban,
    deactivate_all_active_bans,
    deactivate_ban,
    deactivate_extra_active_bans,
    make_ban_id,
    set_appeal_log_msg,
    set_log_message_id,
    set_rejected_by,
    set_review,
    set_review_if_absent,
    update_ban,
)

__all__ = [
    "_bans",
    "active_ban_count",
    "active_ban_user_ids",
    "active_bans_for_users",
    "active_bans_page",
    "clear_review",
    "create_ban",
    "deactivate_all_active_bans",
    "deactivate_ban",
    "deactivate_extra_active_bans",
    "get_active_ban",
    "get_ban",
    "make_ban_id",
    "set_appeal_log_msg",
    "set_log_message_id",
    "set_rejected_by",
    "set_review",
    "set_review_if_absent",
    "update_ban",
    "user_appeal_count",
    "user_appealable_bans",
    "user_ban_count",
    "user_bans",
]
