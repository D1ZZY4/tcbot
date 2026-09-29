# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Inline-keyboard factories, split by domain; this package keeps the old module path."""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from .admin import demote_confirm_kb, promo_decision_kb, promote_role_kb
from .appeal import appeal_cancel_kb, appeal_review_kb
from .ban import (
    action_proof_kb,
    appeal_button_kb,
    ban_log_new,
    ban_log_update,
    ban_update_confirm_kb,
    detail_kb,
)
from .check import _WARN_GROUP_TITLE_MAX as _WARN_GROUP_TITLE_MAX
from .check import (
    check_back_row,
    check_profile_kb,
    check_warn_groups_kb,
    check_warns_back_row,
    checkme_ban_kb,
    checkme_detail_back_kb,
)
from .common import _build_topic_rows as _build_topic_rows
from .common import _https_url as _https_url
from .drills import (
    paged_drill_kb,
    stats_list_kb,
    stats_search_panel_kb,
    stats_search_results_kb,
    stats_search_row,
)
from .flows import connect_join_kb, proof_step_kb, reason_step_kb
from .language import language_list_kb
from .menus import (
    additional_menu_kb,
    back_to_start_kb,
    group_start_kb,
    groups_menu_kb,
    main_menu_kb,
    tcgroups_kb,
)
from .stats import stats_back_kb, stats_back_row, stats_main_kb
from .topics import (
    back_to_help_cmd_kb,
    back_to_help_kb,
    back_to_module_kb,
    back_to_privacy_policy_kb,
    help_topics_kb,
    help_topics_menu_kb,
    module_help_kb,
    privacy_kb,
    privacy_policy_sections_kb,
)

__all__ = [
    "InlineKeyboardButton",
    "InlineKeyboardMarkup",
    "action_proof_kb",
    "additional_menu_kb",
    "appeal_button_kb",
    "appeal_cancel_kb",
    "appeal_review_kb",
    "back_to_help_cmd_kb",
    "back_to_help_kb",
    "back_to_module_kb",
    "back_to_privacy_policy_kb",
    "back_to_start_kb",
    "ban_log_new",
    "ban_log_update",
    "ban_update_confirm_kb",
    "check_back_row",
    "check_profile_kb",
    "check_warn_groups_kb",
    "check_warns_back_row",
    "checkme_ban_kb",
    "checkme_detail_back_kb",
    "connect_join_kb",
    "demote_confirm_kb",
    "detail_kb",
    "group_start_kb",
    "groups_menu_kb",
    "help_topics_kb",
    "help_topics_menu_kb",
    "language_list_kb",
    "main_menu_kb",
    "module_help_kb",
    "paged_drill_kb",
    "privacy_kb",
    "privacy_policy_sections_kb",
    "promo_decision_kb",
    "promote_role_kb",
    "proof_step_kb",
    "reason_step_kb",
    "stats_back_kb",
    "stats_back_row",
    "stats_list_kb",
    "stats_main_kb",
    "stats_search_panel_kb",
    "stats_search_results_kb",
    "stats_search_row",
    "tcgroups_kb",
]
