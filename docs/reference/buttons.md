# Buttons

This page is the reference for every inline keyboard builder in TCF Bot. All
builders live in `tcbot/modules/helper/buttons/` and are re-exported by the
package `__init__.py`, so existing dotted imports keep working. Exact callback
payloads and `WAITING_*` states are in [callbacks.md](callbacks.md); how the
messages that carry these keyboards are rendered is in
[Transport](../flows/transport.md).

## Rendering contract

A button is built as a Kurigram `InlineKeyboardButton` and converted to a rich
`<tg-button>` by `rich/button.py`. A rich button carries exactly one action:

| Keyword | Action type | Notes |
|---|---|---|
| `data` | `callback_data` | At most 64 bytes. |
| `url` | `url` | Public HTTPS link. |
| `copy` | `copy_text` | Copies text on tap. |
| `web_app` | `web_app` | Private chats only. |
| `login_url` | `login_url` | Optional forward text and write access. |
| `switch_inline_query` | `switch_inline_query` | Opens inline mode. |
| `switch_inline_query_current_chat` | `switch_inline_query_current_chat` | Current-chat variant. |
| `switch_inline_query_chosen_chat` | `switch_inline_query_chosen_chat` | With optional chat-type flags. |
| `disabled` | `disabled` | Inert button. |

Convenience wrappers in `rich/button.py` (`callback_button`, `url_button`,
`copy_button`, `web_app_button`, `login_button`, `switch_button`,
`disabled_button`) are thin aliases over `button()`.

Style names map to API values: `default` to none, `blue` to `primary`, `green`
to `success`, `red` to `danger`, and `link` to `link`. Rows hold at most eight
buttons, and an unknown style or alignment is ignored. A single-button row is
the supported way to give a button a whole row.

### Color semantics

| Color | Style | Used for |
|---|---|---|
| Blue | `PRIMARY` | Default for actions, detail opens, navigation, and links. |
| Green | `SUCCESS` | Positive commits: Approve, Agree, proof Done, rules Publish, the selected locale. |
| Red | `DANGER` | Destructive or rejecting actions and every Cancel: Reject, Demote Confirm, rules Delete, Discard, Close, destructive confirmations. |
| Green | `SUCCESS` | Positive navigation: Back, Prev, Next, and the selected locale. |
| None | default | No remaining primary action; plain informational cells stay uncolored. |

Older clients ignore the style field, so color is purely additive.

### Inline keyboard fallback

`buttons_from_markup(reply_markup)` is all-or-nothing: one cell that cannot map keeps
the whole keyboard inline. Every cell action above has a rich equivalent, so a
cell fails to map only when its `callback_data` exceeds 64 bytes, its text is not
a string, or it carries an action outside the mapped set. A cell with no action
is rendered as a disabled rich button. Payloads using `blocks` instead of `html`
are not embedded. This is a transport fallback only; there is no parse-mode send
path.

### Symbol vocabulary

Labels use text arrows and marks, not pictograph emoji. The arrow leads for
backward actions and trails for forward ones; the symbol set is shared across
both catalogs so the same action looks the same in every locale.

| Symbol | Meaning | Buttons |
|---|---|---|
| `⤎` | go back | Back |
| `↤` / `↦` | previous / next, continue | Prev, Continue, Connect, Next |
| `↧` / `↥` | expand / collapse | Details, Simple |
| `🗸` / `🗶` | confirm / refuse | Done, Confirm, Approve, Agree; Cancel, Reject, Delete, Close |
| `↷` | defer | Skip |
| `🗩` | respond to a decision | Appeal, Submit Appeal, View Appeal |
| `↝` / `🖈` | open elsewhere / pinned evidence | View Log, Open in PM, community links; View Proof, Proof id |
| `⤎` + `🗶` | leave a panel | Back (green) and Close (red) on read-only menus |
| `⇧` / `⌫` | create / remove | Publish, Discard |
| `⛁` / `☰` / `✎` | govern / configure / edit | Settings, Manage Rules, Edit Draft, Rename |
| `↑` / `↓` | reorder | Up, Down |
| `+` / `☳` / `☶` | add / more / extra | Add Category, Add Item, More, Additional |
| `🗟` | document preview | Preview |
| `🕬` / `🗪` / `🗫` | announcement / discussion / appeals channel | Main Channel, Discussion Group, Appeals Channel |
| `⌕` | search | Search, New Search |
| `ⓘ` / `◈` | information | Help, Privacy Policy, Preview; About, Privacy, Rules |
| `⌘` | locale | Language |

Read-only menus (stats main, help index, privacy index) carry a Close button
that deletes the panel message. Interactive moderation flows never do, because
closing the prompt would discard an in-flight action. Help section titles join
the module name and section label with `➛`. Command tables use the Alias
header whenever an alias marker is present, and the marker's parentheses are
stripped from the cell.

### Label ownership

Every localized label lives exactly once in `i18n/<locale>/button.toml`.
Locale-dependent builders take an explicit `locale` argument. Role names in the
promotion picker are canonical English identifiers from `ROLE_LABEL`, not
translated prose. `help_topics_menu_btn` and `help_topics_btn` take a `locale`
for their Back and Close controls; their topic names are stable module
identifiers. Builders never hardcode user-facing labels. Builders in `common.py`
and `rules.py` are reached through their submodules rather than the package root.

## Shared helpers (`common.py`, `nav.py`)

| Builder | Emits | Style | Purpose |
|---|---|---|---|
| `back_button`, `back_row(callback_data, locale)` | `back_to_start`, `check_main:*`, `stats_main`, or a module-specific target | green | Single owner of the Back button. |
| `back_markup`, `with_back_row` | same | green | Wrap a Back row alone or append it to other rows. |
| `close_btn(locale)` | `close_msg` | red | Dismiss a read-only panel by deleting its message. |
| `_build_topic_rows` | caller-supplied callbacks | caller-supplied | Pair items into two-column rows. |
| `nav_row(page, total_pages, cb_prefix, locale)` | `<prefix>:<page-1>`, `<prefix>:<page+1>` | green | Prev/Next row for paged views. |

## Moderation (`ban.py`, `flows.py`)

| Builder | Emits | Style |
|---|---|---|
| `ban_log_btn` | Proof and appeal URLs, one per row | blue |
| `ban_update_confirm_btn` | View Log / View Proof URLs (blue), `ban_cancel` (red), `ban_continue` (blue) | mixed |
| `appeal_button_btn` | Appeal deep link URL | blue |
| `action_proof_btn` | Proof URL | blue |
| `join_ban_btn` | View Log / View Proof URLs (blue), appeal URL (blue) on its own row | blue |
| `detail_btn` | Proof / appeal URLs plus a Back callback | blue + none |
| `reason_step_btn(action, skip_allowed)` | `<action>_skip_reason` (blue), `<action>_cancel` (red) | mixed |
| `proof_step_btn(action, skip_allowed)` | `<action>_skip_proof` (blue), `<action>_done_proof` (green), `<action>_cancel` (red) | mixed |
| `connect_join_btn` | `tc_join` (blue), `tc_cancel` (red) | mixed |

Ban proof is mandatory, so the ban flow uses `skip_allowed=False` and emits no
Skip button. Kick, mute, and warn allow Skip. Done and Skip claim the
`{action}_executing` flag synchronously before their first await.

## Roles (`admin.py`)

| Builder | Emits | Style |
|---|---|---|
| `promote_role_btn(target_id, roles, executor_id)` | `promo_role:<role>:<target>[:<executor>]` and `promo_role_cancel:...` | role buttons blue, Cancel red |
| `role_change_btn(target, roles, current, executor_id)` | `role_change:<role>:<target>[:<executor>]` and `role_change_cancel:...` | role buttons blue, Cancel red |
| `demote_confirm_btn(target_id, executor_id)` | `demote_confirm:<target>[:<executor>]` (red), `demote_cancel:...` (red) | mixed |
| `promo_decision_btn(request_id)` | `promo_approve:<id>` (green), `promo_reject:<id>` (red) | mixed |

The optional executor segment lets a handler refuse a different tapper. Legacy
two-part shapes remain valid.

## Appeals (`appeal.py`)

| Builder | Emits | Style |
|---|---|---|
| `appeal_cancel_btn` | `cancel_appeal` | red |
| `appeal_review_btn(ban_id, review_message_id)` | `appeal_approve_<ban>_<review>` (green), `appeal_reject_<ban>_<review>` (red) | mixed |

The review id rides in the payload so an older card cannot decide a newer
appeal; a legacy payload without the suffix falls back to the tapped message id.

## Community rules (`rules.py`)

| Builder | Emits | Style |
|---|---|---|
| `picker_btn(items, selected)` | `rules_step:pick:<id>` (blue), `other` (none), `done` (green), `clear` (none), `cancel` (red) | mixed |
| `editor_panel_btn(has_content)` | `rules_edit_draft` (blue), `rules_preview` (blue), Upload .md (blue), Back to language (green), Close; adds `rules_publish` (green) and `rules_discard` (red) only when the draft has items | mixed |
| `preview_btn` | Back to the editor panel + Close for the draft preview | mixed |
| `categories_btn` | `rules_cat:<key>`, rename/up/down (blue), `rules_cat_del:<key>` (red), `rules_cat_add` (blue), Back + Close | mixed |
| `items_btn` | `rules_item_add` (blue), Back + Close | mixed |
| `confirm_btn(yes, no)` | destructive confirmation: Yes (red), No (red), Back + Close | mixed |
| `prompt_btn(back)` | Back + Close for a text-entry step | mixed |
| `rules_index_btn(categories, locale, page)` | `rules_show:<key>`, `rules_index:<n>` | mixed |
| `category_sections_btn(sections, locale)` | `rules_section:<n>`, Back + Close | mixed |
| `rules_page_btn(...)` | `rules_prev:<n>`, `rules_next:<n>` | green |
| `ack_btn(version, member)` | `rules_ack:<version>:<member>` | green |

Category slugs are capped at 40 characters so even the longest callback and a
collision suffix stay within 64 bytes.

## Check and statistics (`check.py`, `stats.py`, `drills.py`)

| Builder | Emits | Style |
|---|---|---|
| `check_profile_btn` | Bans, Appeals, Warnings, Kicks, Mutes drill-downs | blue |
| `check_warn_groups_btn` | `check_warn_chat:<target>:<chat>:0` | blue |
| `checkme_ban_btn` | Details, Proof URL, Appeal URL | blue |
| `checkme_detail_back_btn` | Proof URL, Back | blue + none |
| `stats_main_btn(show_staff, show_users)` | Roster, Bans, Chats (blue); Users (blue, Owner only) | blue |
| `stats_search_row` | `stats_bans_search` | blue |
| `stats_search_panel_btn` | `stats_search_cancel` | red |
| `stats_search_results_btn` | Legacy numbered hits; no production caller | mixed |
| `paged_drill_btn`, `stats_list_btn` | Legacy numbered grid; no production caller | mixed |
| `stats_list_nav_btn` | `nav_row` (Prev/Next), optional Search row, Back (green); no numbered buttons | mixed |
| `stats_search_results_nav_btn` | New Search (blue), Back (green) | mixed |

`stats_list_nav_btn` and `stats_search_results_nav_btn` are the live table
builders. The numbered builders remain only as exported legacy helpers and for
their keyboard tests. Item callbacks may carry a stable entity id so a list
mutation between render and tap cannot show a different record. Legacy
three-part callbacks still work.

## Menus, help, and language (`menus.py`, `topics.py`, `language.py`)

| Builder | Emits | Style |
|---|---|---|
| `main_menu_btn` | About, Help, Additional, Privacy, Language | blue |
| `group_start_btn` | Open PM URL, `help_menu_group` | blue |
| `open_pm_btn(bot_username, start, locale)` | Shared Open in PM button; the caller chooses the deep-link target | blue |
| `additional_menu_btn` | Main Channel URL alone, then Discussion Group and Appeals URLs, then Logs URL, then Back | blue + none |
| `groups_menu_btn`, `tcgroups_btn` | Detailed/Simple toggle | blue |
| `help_topics_menu_btn`, `help_topics_btn`, `module_help_btn` | `helpc_*`, `helps_<module>:<index>` | blue |
| `privacy_btn`, `privacy_policy_sections_btn` | `privacy_policy_menu`, `privacy_section_<n>`, Back | blue + none |
| `language_list_btn(scope, items, selected)` | `lang:set:<scope>:<code>` | blue, selected green |

A URL button is dropped when its resolved link is empty, so no dead button is
sent. The selected locale gets a green style and a checkmark text prefix.

## Parsing and freshness

`callback_is_current()` compares `query.message.chat.id` and
`query.message.message_id` with the values recorded at flow entry and fails
closed when no integer identity was recorded. Stale taps are answered and
discarded. The freshness keys per call site and the payload parsers are listed
in [callbacks.md](callbacks.md#parsing-and-freshness).

Privileged callbacks re-authorize at tap time: role prompts carry the opener as
an executor segment, stats panes re-check rank, and rules editor actions
re-check `rules.manage`. See [Permissions](../flows/permissions.md).

## Validation

```bash
uv run pytest tests/ -q -k keyboard
```

Relevant tests include `tests/test_keyboards.py`, `tests/test_drill_kb.py`,
`tests/test_keyboard_locale_contract.py`, `tests/test_rich_modules.py`, and
`tests/test_callback_freshness.py`.
