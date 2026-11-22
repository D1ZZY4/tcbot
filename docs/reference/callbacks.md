# Callbacks and states

This page is the exhaustive registry of `WAITING_*` conversation states and
`callback_data` namespaces. Names and patterns are exact; do not introduce
parallel spellings. The callback registry also covers button conventions that
were formerly in a separate button-styles reference.

## Conversation states

| Domain | Constant | Value | Owner |
|---|---|---|---|
| Ban | `WAITING_PROOF` | 0 | `pipelines/ban_flow.py` |
| Ban | `WAITING_UPDATE_CONFIRM` | 1 | `pipelines/ban_flow.py` |
| Ban rules | `WAITING_BAN_RULES` | 2 | `pipelines/ban_rules_step.py` |
| Ban rules | `WAITING_BAN_RULES_NOTE` | 3 | `pipelines/ban_rules_step.py` |
| Kick, mute, warn | `WAITING_REASON` | 0 | `pipelines/reason_flow.py` |
| Kick, mute, warn | `WAITING_PROOF` | 1 | `pipelines/reason_flow.py` |
| Kick, mute, warn | `WAITING_RULES` | 2 | `pipelines/reason_flow.py` |
| Kick, mute, warn | `WAITING_RULES_NOTE` | 3 | `pipelines/reason_flow.py` |
| Rules editor | `WAITING_EDITOR_MENU` | 0 | `pipelines/rules_flow.py` |
| Rules editor | `WAITING_CONFIRM_DISCARD` | 5 | `pipelines/rules_flow.py` |
| Appeal | `WAITING_APPEAL` | 0 | `pipelines/appeal_submit_flow.py` |

`check_flow.py`, `stats_flow.py`, and other flows define no `WAITING_*` state.
Stats search uses `ctx.user_data` keys instead.

## Callback namespace by domain

The `Built by` column names the keyboard factory; `Handled by` names the module
whose `CallbackQueryHandler` pattern matches it.

### Ban

| Callback pattern | Built by | Handled by |
|---|---|---|
| `ban_cancel` | `buttons/ban.py`, `buttons/flows.py` | `ban_flow.py` with `^ban_cancel$`; `rules_step:cancel` also stops the rules step. |
| `ban_continue` | `buttons/ban.py::ban_confirm_btn` | `ban_confirmation.py` with `^ban_continue$`. |
| `ban_done_proof` | `buttons/flows.py::proof_step_btn` | `ban_flow.py` with `^ban_done_proof$`. |
| `rules_step:pick:<id>` | `buttons/rules.py::picker_btn` | `ban_rules_step.py` and `reason_flow.py`. |
| `rules_step:done`, `other`, `clear`, `cancel` | `buttons/rules.py::picker_btn` | `ban_rules_step.py` and `reason_flow.py`. The rules editor fallback handles `rules_step:cancel` only. |

`buttons/ban.py` also builds URL-only buttons with no `callback_data`:
`action_proof_btn`, `appeal_button_btn`, `join_ban_btn`, `detail_btn`.

### Kick, mute, and warn

| Callback pattern | Handled by |
|---|---|
| `<action>_cancel` for `kick`, `mute`, `warn` | `reason_flow.py` with `^<action>_cancel$`. |
| `<action>_skip_reason` | Registered only when `skip_allowed`; all three consumers use `False`, so it is not emitted. |
| `<action>_skip_proof` | Emitted by `proof_step_btn` for kick, mute, and warn (default `skip_allowed=True`) and handled by `reason_flow.py`; suppressed only for ban. |
| `<action>_done_proof` | `reason_flow.py` with `^<action>_done_proof$`. |
| `rules_step:*` | `reason_flow.py` in `WAITING_RULES` and its fallback. |

### Appeals

| Callback pattern | Built by | Handled by |
|---|---|---|
| `appeal_approve_<ban_id>_<review_message_id>` | `buttons/appeal.py` | `appeals.py` then `AppealReviewMixin.on_decision`. |
| `appeal_reject_<ban_id>_<review_message_id>` | `buttons/appeal.py` | Same handler. |
| `appeal_approve_<ban_id>`, `appeal_reject_<ban_id>` | Legacy cards without suffix | Same handler; falls back to the tapped message id. |
| `cancel_appeal` | `buttons/appeal.py::appeal_cancel_btn` | `appeal_submit_flow.py`. |

### Roles

| Callback pattern | Built by | Handled by |
|---|---|---|
| `promo_approve:<id>`, `promo_reject:<id>` | `buttons/admin.py::promo_decision_btn` | `admins.py`. |
| `promo_role:<role>:<target_id>[:<executor_id>]` | `buttons/admin.py::promote_role_btn` | `admins.py`. |
| `promo_role_cancel:<target_id>[:<executor_id>]` | `buttons/admin.py::promote_role_btn` | `admins.py`. |
| `demote_confirm:<target_id>[:<executor_id>]` | `buttons/admin.py::demote_confirm_btn` | `admins.py`. |
| `demote_cancel:<target_id>[:<executor_id>]` | `buttons/admin.py::demote_confirm_btn` | `admins.py`. |

The optional executor segment lets a handler refuse a different tapper. Legacy
two-part shapes remain valid.

### Rules

| Callback pattern | Built by | Handled by |
|---|---|---|
| `rules_ack:<version>:<member>` | `buttons/rules.py::ack_btn` | `rules.py`. |
| `rules_show:<key>` | `buttons/rules.py::rules_menu_btn` | `rules.py`. |
| `rules_menu`, `rules_page:<n>` | `buttons/rules.py` | `rules.py`. |
| `rules_edit_draft`, `rules_panel`, `rules_preview`, `rules_publish`, `rules_settings`, `rules_discard` | `editor_panel_btn`, `categories_btn` | `rules_flow.py` menu state. |
| `rules_discard_yes`, `rules_discard_no` | `buttons/rules.py::confirm_btn` | `rules_flow.py` discard state. |
| `rules_cat:<key>`, `rules_cat_add`, `rules_cat_rename:<key>`, `rules_cat_up:<key>`, `rules_cat_down:<key>`, `rules_cat_del:<key>` | `buttons/rules.py::categories_btn` | `rules_flow.py` menu state. |
| `rules_item_add`, `rules_categories` | `buttons/rules.py::items_btn` | `rules_flow.py` menu state. |

### Check and statistics

| Callback family | Purpose |
|---|---|
| `checkme_detail:<ban_id>`, `checkme_back:<ban_id>` | Self-status detail and back. |
| `check_main:<target>`, `check_bans:<target>:<page>`, `check_ban_item:<target>:<ban>` | Profile and ban drill-downs. |
| `check_warns:<target>`, `check_warn_chat:<target>:<chat>:<page>` | Warning drill-downs. |
| `check_kicks:<target>:<page>`, `check_mutes:<target>:<page>`, `check_appeals:<target>:<page>` | Event histories. |
| `stats_main`, `stats_admins`, `stats_users:<page>`, `stats_chats:<page>`, `stats_bans:<page>` | Overview and lists. |
| `stats_user_item`, `stats_chat_item`, `stats_ban_item` | Paged detail cards with a stable id segment. |
| `stats_bans_search`, `stats_search_item`, `stats_search_back`, `stats_search_cancel` | Ban search. |

### Menus, help, and language

| Callback pattern | Handled by |
|---|---|
| `about_menu`, `additional_menu` | `about.py`, `additional.py`. |
| `help_menu`, `help_menu_group`, `helpc_main`, `help_<module>`, `helpc_<module>`, `helps_<module>:<index>`, `helpcs_<module>:<index>` | `help.py`. |
| `privacy_menu`, `privacy_policy_menu`, `privacy_section_<n>` | `privacy.py`. |
| `back_to_start`, `close_msg`, `menu_groups`, `menu_groups_simple`, `menu_groups_details` | `start.py`. |
| `groups_details`, `groups_simple` | `groups.py`. |
| `language_menu`, `lang:list:(user|group)`, `lang:set:<scope>:<code>` | `language.py`. |

### Connection

`tc_join` and `tc_cancel` are emitted by `buttons/flows.py::connect_join_btn`
and handled by `connect.py` through `connected_flow.on_join_decision`.

## Button conventions

Which builder emits each callback, its color, and its label key are in
[buttons.md](buttons.md). That page also owns the rich-button action types,
the 64-byte callback limit, the semantic color palette, the all-or-nothing
inline fallback, and the rule that every label lives once in `button.toml`.
This page stays focused on the payload grammar and the state registry.

## Parsing and freshness

`messages/rich_edit.py` owns `callback_args`, `callback_args_optional`, and
`callback_numbers`; all validate segment counts before indexing. `callback_is_current()`
compares `query.message.chat.id` and `query.message.message_id` with the values
recorded at flow entry and is permissive when no integer identity was recorded.
Stale taps are answered and discarded.

| Call site | Freshness keys |
|---|---|
| `reason_flow.py::_callback_is_live` | `<action>_prompt_chat`, `<action>_prompt_id`. |
| `ban_confirmation.py::stale_ban_callback` | `ban_prompt_chat_id`, `ban_prompt_msg_id`. |
| `ban_rules_step.py` | Calls `stale_ban_callback()` before each action. |
| `appeal_submit_flow.py::_on_cancel` | Inline check of `appeal_instruction_msg_id`. |
