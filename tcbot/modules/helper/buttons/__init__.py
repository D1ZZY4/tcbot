# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Inline-keyboard factories, split by domain; this package keeps the old module path."""

from __future__ import annotations

from tcbot.modules.helper.buttons.admin import (
    demote_confirm_btn,
    promo_decision_btn,
    promote_role_btn,
    role_change_btn,
)
from tcbot.modules.helper.buttons.appeal import appeal_cancel_btn, appeal_review_btn
from tcbot.modules.helper.buttons.ban import (
    action_proof_btn,
    appeal_button_btn,
    ban_log_btn,
    ban_update_confirm_btn,
    detail_btn,
    join_ban_btn,
)
from tcbot.modules.helper.buttons.check import (
    check_back_markup,
    check_back_row,
    check_paged_markup,
    check_profile_btn,
    check_warn_groups_btn,
    check_warns_back_row,
    checkme_ban_btn,
    checkme_detail_back_btn,
)
from tcbot.modules.helper.buttons.drills import (
    paged_drill_btn,
    stats_list_btn,
    stats_list_nav_btn,
    stats_search_panel_btn,
    stats_search_results_btn,
    stats_search_results_nav_btn,
    stats_search_row,
)
from tcbot.modules.helper.buttons.flows import (
    connect_join_btn,
    connect_verify_btn,
    proof_step_btn,
    reason_step_btn,
)
from tcbot.modules.helper.buttons.language import language_list_btn
from tcbot.modules.helper.buttons.menus import (
    additional_menu_btn,
    back_to_start_btn,
    group_start_btn,
    groups_menu_btn,
    main_menu_btn,
    open_pm_btn,
    tcgroups_btn,
)
from tcbot.modules.helper.buttons.nav import nav_row
from tcbot.modules.helper.buttons.stats import (
    stats_back_btn,
    stats_main_btn,
)
from tcbot.modules.helper.buttons.topics import (
    about_sections_btn,
    back_to_about_btn,
    back_to_help_btn,
    back_to_help_cmd_btn,
    back_to_module_btn,
    back_to_privacy_policy_btn,
    help_topics_btn,
    help_topics_menu_btn,
    module_help_btn,
    privacy_btn,
    privacy_policy_sections_btn,
)

__all__ = [
    "about_sections_btn",
    "action_proof_btn",
    "additional_menu_btn",
    "appeal_button_btn",
    "appeal_cancel_btn",
    "appeal_review_btn",
    "back_to_about_btn",
    "back_to_help_btn",
    "back_to_help_cmd_btn",
    "back_to_module_btn",
    "back_to_privacy_policy_btn",
    "back_to_start_btn",
    "ban_log_btn",
    "ban_update_confirm_btn",
    "check_back_markup",
    "check_back_row",
    "check_paged_markup",
    "check_profile_btn",
    "check_warn_groups_btn",
    "check_warns_back_row",
    "checkme_ban_btn",
    "checkme_detail_back_btn",
    "connect_join_btn",
    "connect_verify_btn",
    "demote_confirm_btn",
    "detail_btn",
    "group_start_btn",
    "groups_menu_btn",
    "help_topics_btn",
    "help_topics_menu_btn",
    "join_ban_btn",
    "language_list_btn",
    "main_menu_btn",
    "module_help_btn",
    "nav_row",
    "open_pm_btn",
    "paged_drill_btn",
    "privacy_btn",
    "privacy_policy_sections_btn",
    "promo_decision_btn",
    "promote_role_btn",
    "proof_step_btn",
    "reason_step_btn",
    "role_change_btn",
    "stats_back_btn",
    "stats_list_btn",
    "stats_list_nav_btn",
    "stats_main_btn",
    "stats_search_panel_btn",
    "stats_search_results_btn",
    "stats_search_results_nav_btn",
    "stats_search_row",
    "tcgroups_btn",
]
