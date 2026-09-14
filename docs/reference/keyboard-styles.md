# Keyboard Styles Reference

For module structure, see [`../architecture/modules.md`](../architecture/modules.md).
For shared helpers, see [`../architecture/helpers.md`](../architecture/helpers.md).
For conversation flows that consume these keyboards, see
[`../architecture/workflows.md`](../architecture/workflows.md).

Every inline keyboard the bot sends is built from a factory in
`tcbot/modules/helper/keyboards.py` or a workflow-local helper next to the flow
that owns the state. This document is the single source of truth for callback
data, button labels, ownership, and the conventions the team follows.

It is intentionally flexible: when a new feature lands, add a row to the table
that fits its surface, follow the conventions, and the documentation stays
useful without becoming a checklist of every keystroke.

---

## Conventions

| Topic | Rule |
|---|---|
| Source of truth | `tcbot/modules/helper/keyboards.py` for reusable builders. Workflow-local builders are allowed when callback state is private to the workflow (`stats_flow.py`, `check_flow.py`, conversation flows). |
| Labels | Short, title-case labels loaded from `i18n/<locale>/button.toml` through `t("button.*", locale, plain=True)`; rendered in the resolved locale, no pictograph emoji. `«` and `»` are allowed for navigation arrows. |
| Colors | Semantic `style`: `SUCCESS` (green) for Approve, `DANGER` (red) for Reject and destructive Confirm, `PRIMARY` (blue) for continue/select steps (`Connect`, `Continue`, role options, `Skip`), numbered drill-in buttons, Proof/Appeal URL buttons, and every start-menu option (main menu, help topics, module sections, privacy entries, community links, group toggles, the Language rows, `Open in PM`). Cancel, `« Back`, the `« Prev` / `Next »` nav row, `Done`, and the re-ban card's View Log / View Proof links stay unstyled. Older clients render the same buttons without color, so styling never carries meaning alone. |
| Localization | Every keyboard factory takes `locale` and reads its labels from the catalog (`button.*` keys, `plain=True`). Thread the resolved handler locale through every call site; labels render in the viewer's locale. |
| Back navigation | `« Back` always returns one step. Nested views use `back_to_module_kb` / `back_to_help_kb` / `back_to_help_cmd_kb` / `back_to_privacy_policy_kb`. |
| Pagination | Numbered drill-in buttons three per row, then `« Prev` and `Next »` on a single nav row (only when more than one page), then optional global actions, then `« Back`. |
| Confirmation | Positive action first, `Cancel` second on the same row: `[Confirm] [Cancel]`, `[Approve] [Reject]`, `[Connect] [Cancel]`. The re-ban update card is the one exception, with `Cancel` first: `[Cancel] [Continue]`. |
| External links | Use `url=` only for external navigation (proof links, appeal deep links, public usernames). All other buttons use `callback_data`. |
| Identity-aware copy | Refusal lines and staff notices belong in `tcbot/modules/helper/identity.py`, never inlined in keyboard factories. |
| Async edits | Callback handlers `await q.answer()` first, then `safe_edit_cb()` from `parse_editmsg.py` to swallow benign `Message is not modified` errors. |
| Callback budget | Telegram allows up to 64 bytes of `callback_data`. Use short namespace prefixes and integer IDs; avoid embedding free text. |

---

## Callback-data namespaces

Each feature owns a namespaced callback prefix. The first segment is always
the prefix; subsequent segments are typed positional fields separated by `:`
or `_` as listed in each row below.

| Namespace | Owner | Shape | Notes |
|---|---|---|---|
| `back_to_start` | start menu | flat | Returns to `/start` PM landing. |
| `about_menu` / `additional_menu` / `help_menu` / `privacy_menu` / `privacy_policy_menu` / `language_menu` | start menu | flat | Top-level menu transitions. |
| `privacy_section_<idx>` | privacy policy | integer index | Renders one of the six privacy policy sections (0-5). Produced by `privacy_policy_sections_kb()`. |
| `privacy_policy_menu` | privacy policy | flat | Opens the policy section index; the section-view `« Back` from `back_to_privacy_policy_kb()` reuses this callback to return to the index. The index's own `« Back` returns to `privacy_menu`. |
| `help_menu_group` | start in groups | flat | Alert-only: points users to `/help`. |
| `helpc_main` | `/help` command | flat | Returns to the command-path help index. |
| `help_<mod>` | help menu path | one segment | Module overview reached from the start menu. |
| `helpc_<mod>` | help command path | one segment | Module overview reached from `/help`. |
| `helps_<mod>:<idx>` | help menu path | mod, section idx | Sub-section of a module overview reached via `/start` → Help. |
| `helpcs_<mod>:<idx>` | help command path | mod, section idx | Sub-section of a module overview reached via `/help`. |
| `lang:list:<scope>` / `lang:set:<scope>:<locale>` | language panel | scope or scope + locale | Opens the locale option list and applies a tapped locale; `scope` is `user` (PM) or `group` and must match the chat type. The start-menu path's Back row returns to `back_to_start`; the command path omits it. Produced by `language_list_kb()`. |
| `menu_groups` / `menu_groups_simple` / `menu_groups_details` | start menu | flat | Connected-groups list with view toggles. |
| `groups_simple` / `groups_details` | `/tcgroups` | flat | Local toggle for the standalone groups list. |
| `tc_join` / `tc_cancel` | group connect prompt | flat | Group owner accepts or rejects the federation join. Configurable on `BuildConnection`. |
| `<action>_skip_reason` / `<action>_skip_proof` / `<action>_done_proof` / `<action>_cancel` | conversation flows | one segment | Generated by `BuildReason` / `BuildProof` for ban / kick / mute / warn. |
| `ban_continue` | re-ban confirmation | flat | Proceed from the update-confirm card to proof collection (reuses the shared `ban_cancel` abort path). |
| `appeal_approve_<ban_id>` / `appeal_reject_<ban_id>` | appeal review | ban ID tail | Staff verdict on a submitted appeal. Both buttons use the underscore-delimited `<action>_<ban_id>` shape that the handler registers and parses (`appeals.py` pattern `^appeal_(approve|reject)_\S+$`; `appeal_review_flow.py` parses the tail after `appeal_reject_`); appeal IDs cannot contain the separator. |
| `cancel_appeal` | appeal submit | flat | Cancels an appeal submission from the instruction prompt. Produced by `appeal_cancel_kb()`. |
| `promo_role:<role>:<target_id>` | promote menu | role, target | Inline role-selection menu shown when `/tcpromote` is run without a role argument. |
| `promo_role_cancel:<target_id>` | promote menu | target | Cancel the role-selection menu. |
| `promo_approve:<request_id>` / `promo_reject:<request_id>` | Founder DM | request | Founder resolves a pending Admin promotion request. |
| `demote_confirm:<target_id>` / `demote_cancel:<target_id>` | demote prompt | target | Confirm or cancel a demotion. |
| `checkme_detail:<ban_id>` / `checkme_back:<ban_id>` | `/checkme` | ban | Toggle the `/checkme` summary and detail views. |
| `stats_main` / `stats_admins` / `stats_users:<page>` / `stats_user_item:<page>:<idx>[:stable]` / `stats_chats:<page>` / `stats_chat_item:<page>:<idx>[:stable]` / `stats_bans:<page>` / `stats_ban_item:<page>:<idx>[:stable]` | `/tcstats` | varies | Federation stats drill-downs (`Stats` class). |
| `stats_bans_search` / `stats_search_cancel` / `stats_search_back` / `stats_search_item:<idx>` | stats search | varies | Search panel for the active-ban list. |
| `check_main:<uid>` | `/check` | target | Top-level profile (used by every drill-down's `« Back`). |
| `check_bans:<uid>:<page>` / `check_ban_item:<uid>:<ban_id>` | `/check` | target, page or ban | Bans drill-down list and per-record detail. |
| `check_appeals:<uid>:<page>` | `/check` | target, page | Appeals drill-down list; items reuse `check_ban_item`. |
| `check_warns:<uid>` / `check_warn_chat:<uid>:<chat_id>:<page>` | `/check` | target, optional chat + page | Warnings overview and per-chat list. |
| `check_kicks:<uid>:<page>` / `check_mutes:<uid>:<page>` | `/check` | target, page | Kicks and mutes drill-downs. |

When a feature reuses an existing prefix (e.g. `check_ban_item` from the
appeals view), reuse it. Do not introduce a parallel namespace for the same
record type.

---

## Common row layouts

### Flat menu (top-level start)

```text
[ About ]      [ Help ]
[ Additional ] [ Privacy ]
[ Language ]
```

### Binary decision

```text
[ Confirm ]    [ Cancel ]
```

`Confirm` uses `DANGER` when it destroys state (demote) and the decision pair uses `SUCCESS` / `DANGER` (`Approve` / `Reject`); `Cancel` stays neutral. The start-menu groups toggle shares one row with `« Back` (`[ Details ] [ « Back ]`), as do search results actions (`[ New Search ] [ Cancel ]`).

### Module help with sub-sections

```text
[ Section 1 ] [ Section 2 ]
[ Section 3 ] [ Section 4 ]
[ Section 5 ]
[ « Back ]
```

`module_help_kb()` pairs sub-sections two per row and appends `« Back` last.

### Paginated list with detail buttons

```text
[ 1 ] [ 2 ] [ 3 ]
[ 4 ] [ 5 ]
[ « Prev ] [ Next » ]
[ Search ]              ← optional global action
[ « Back ]
```

Used by `/tcstats` bans and `/check` drill-downs. Numbered buttons open the
record detail; `« Back` returns to the parent. One shared factory owns this
shape: `keyboards.paged_drill_kb(items, page=..., total_pages=...,
nav_prefix=..., back_callback=..., extra_rows=...)` builds the numbered grid
(`PRIMARY`, 3 per row), the `nav_row`, optional extra rows, and the neutral
`« Back` last; stats and check drill-downs pass their own labels, callbacks,
and back targets instead of rebuilding it locally.

### Detail view with optional URL buttons

```text
[ View Proof ]          ← URL, only when proof exists
[ View Appeal ]         ← URL, only when an appeal link exists
```

Proof and appeal links stack one per row so proof labels that embed the
target ID never truncate on narrow clients (`ban_log_new()`,
`ban_log_update()`, `appeal_button_kb()`, `action_proof_kb()`); the posted
ban log carries no `« Back`. The `/checkme` detail view pairs an optional
Proof URL with its own `« Back` row instead (`checkme_detail_back_kb()`),
and the drill-down detail views end with `paged_drill_kb`'s `« Back`.

### Privacy policy section index

```text
[ What We Collect ]      [ Why We Collect It ]
[ Who Can Access It ]    [ How Long We Keep It ]
[ Your Rights ]          [ Contact ]
[ « Back ]
```

Produced by `privacy_policy_sections_kb(section_labels, locale)` in
`keyboards.py`. Each button carries `callback_data=f"privacy_section_{idx}"`.
Tapping a section renders the section text with a
`back_to_privacy_policy_kb()` back button.

### Conversation flow keyboards (`BuildReason`, `BuildProof`)

```text
[ Skip ]   [ Cancel ]                   ← reason step (BuildReason.keyboard)
[ Skip ]   [ Done ]   [ Cancel ]        ← proof step (BuildProof.keyboard)
```

`Skip` is omitted when skip is disallowed (warn requires reason), and `Done`
collects everything buffered and executes; both flows put all buttons on a
single row. The action prefix lives in the callback (`ban_skip_reason`,
`mute_done_proof`, `warn_cancel`, etc.) so the flow factory can wire it back
to its own state.

---

## Adding a new keyboard

1. Pick a namespace prefix that is short, lowercase, and unambiguous.
2. Add the factory to `keyboards.py` if it is reusable, or keep it next to the
   workflow if its callback state is private.
3. Register a `CallbackQueryHandler` with a precise regex pattern in the
   module's `__handlers__` list. Anchor with `^…$` and require digits where
   applicable so `helps_<mod>:<idx>` is never confused with `help_<mod>`.
4. The handler awaits `q.answer()` first, then either `safe_edit_cb()` for
   in-place edits or `q.edit_message_text(...)` directly when you have already
   handled the not-modified case.
5. Document the new namespace in the table above.

---

## Anti-patterns

- Defining inline keyboards inside command handlers when an equivalent factory
  already exists in `keyboards.py`.
- Free-text callback data such as `f"approve user {fname}"`.
- Using `:` and `_` interchangeably inside one feature's namespace; pick one
  and stick with it.
- Pictograph emoji in labels.
- Leaving the `« Back` button off a non-root view.
- Rebuilding navigation rows that should come from `module_help_kb` /
  `back_to_module_kb` / `back_to_help_kb` / `back_to_help_cmd_kb`.
