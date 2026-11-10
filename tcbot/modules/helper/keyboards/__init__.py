# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Inline-keyboard factories, split by domain; this package keeps the old module path."""

from __future__ import annotations

from tcbot.modules.helper.keyboards.admin import (
    demote_confirm_kb,
    promo_decision_kb,
    promote_role_kb,
)
from tcbot.modules.helper.keyboards.appeal import appeal_cancel_kb, appeal_review_kb
from tcbot.modules.helper.keyboards.ban import (
    action_proof_kb,
    appeal_button_kb,
    ban_log_kb,
    ban_update_confirm_kb,
    detail_kb,
)
from tcbot.modules.helper.keyboards.check import (
    check_back_markup,
    check_back_row,
    check_paged_markup,
    check_profile_kb,
    check_warn_groups_kb,
    check_warns_back_row,
    checkme_ban_kb,
    checkme_detail_back_kb,
)
from tcbot.modules.helper.keyboards.drills import (
    paged_drill_kb,
    stats_list_kb,
    stats_search_panel_kb,
    stats_search_results_kb,
    stats_search_row,
)
from tcbot.modules.helper.keyboards.flows import (
    connect_join_kb,
    proof_step_kb,
    reason_step_kb,
)
from tcbot.modules.helper.keyboards.language import language_list_kb
from tcbot.modules.helper.keyboards.menus import (
    additional_menu_kb,
    back_to_start_kb,
    group_start_kb,
    groups_menu_kb,
    main_menu_kb,
    tcgroups_kb,
)
from tcbot.modules.helper.keyboards.nav import nav_row
from tcbot.modules.helper.keyboards.stats import (
    stats_back_kb,
    stats_back_row,
    stats_main_kb,
)
from tcbot.modules.helper.keyboards.topics import (
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
