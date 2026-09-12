# Language Preferences

This document describes the per-user and per-group locale system: the TOML
translation catalog, the `utils/i18n.py` engine, locale persistence, the
`/language` command and selection flow, the start-menu entry point, and
how every user-facing surface renders in the resolved locale.

For shared helpers, see [`../../architecture/helpers.md`](../../architecture/helpers.md).
For runtime utilities, see [`../../architecture/utilities.md`](../../architecture/utilities.md).
For the database layer, see [`../../architecture/database.md`](../../architecture/database.md).

## Purpose

Users set a personal locale (used in private chats); groups hold their own
locale (used for group-visible messages), changeable only by the group
owner or federation staff. Only `en-US` ships today; the architecture
accepts new locales as data files with no Python changes.

## Commands and callbacks

| Command | Alias | Purpose | Access |
|---|---|---|---|
| `/language` | `/lang`, `/langs` | Show the language panel for this chat. | Anyone (own preference); group changes need owner/staff. |

| Callback | Purpose |
|---|---|
| `language_menu` | Open the personal panel from the start menu. |
| `lang:list:<scope>` | Re-render the option list (`scope` is `user` or `group`). |
| `lang:set:<scope>:<locale>` | Save the locale and edit the panel into a confirmation. |

The start menu (`main_menu_kb`) carries a bottom-row `Language` button
wired to the same panel renderer as the command; there is no second
implementation.

## User flow and staff flow

1. The caller runs `/lang` (or taps `Language`): in PM the personal
   panel renders in the user locale, in groups the group panel renders
   in the group locale, each with one button per available locale.
2. Tapping a language validates the code, checks group permission when
   the scope is `group`, persists the choice, and edits the panel into
   a confirmation in the newly chosen language.
3. Unknown locale taps answer with the unavailable notice; denied group
   taps answer with the permission notice. Neither edits the panel.

## Locale resolution

`resolve_locale()` in `tcbot/utils/i18n.py` owns precedence: explicit
locale first, then the user locale in private chats or the group locale
in group-like chats, then `en-US`. Unknown or absent values fall through
to `en-US`; resolution never raises.

Handlers resolve once per update via `helper.locale.locale_for_update`
(PM reads the sender, groups read the group row); direct messages use
`locale_for_user`, updateless event paths use `locale_for_chat`. Locale
reads are L1-cached (300 s TTL, invalidated on write). Flows carry the
moderator locale in conversation state and resolve the target locale
fresh for user DMs.

## Coverage

Every user-facing surface renders in the resolved locale: command
replies and alerts, conversation prompts and keyboards, executor
summaries and result cards, profile and drill-down views, the `/help`
system (per-request rebuild via each module's `get_help(locale)`),
identity refusals and notices, and all button labels (`button.toml`
owns every label exactly once).

Stays English by design: audit-log channel posts, staff operational
messages (demotion warnings, enforcement logs), infra error reports,
and log labels. Reason and proof records store the moderator's raw
text; only the surrounding prose translates.

## Database impact

- `user_settings` collection (`{user_id}`, unique): one row per user
  with an explicit preference. Clearing deletes the row. Never touches
  `member_cache`, so preference-only users cannot inflate user counts
  or appear in listings. Unique index on `user_id` in `ensure_indexes`.
- `federated_groups.locale`: optional field on the group row (no new
  collection, no new index; reads filter on the indexed `chat_id`).
  Clearing unsets the field. Groups without a row cannot hold a locale.
- Both helpers store codes verbatim; validity is enforced at the
  command layer and defensively at resolution time.

## Logging behavior

Missing translation keys log at error level and render as `[key]`
(never empty, never an exception). Placeholder mismatches and `None`
values raise `I18nError`. DB failures log at debug/exception level and
surface the generic retry notice.

## Edge cases

- Unknown locale codes (including stale DB values for removed locales)
  resolve to `en-US`.
- Crafted cross-scope taps (`user` scope in a group and vice versa) are
  answered and ignored.
- Non-connected groups cannot hold a locale; the command explains why.
- Anonymous-admin senders fail the creator check and are denied like
  any non-privileged user (fail closed).
- Malformed TOML fails fast at load with the file and reason named.

## Validation hints

```bash
uv run --with pytest pytest tests/test_i18n.py -q
```

The suite locks catalog loading, fallback, placeholder escaping and
`Safe` passthrough, resolution precedence, persistence round-trips and
isolation, permission matrix, aliases, callback shapes, the start-menu
button row, and MarkdownV2-clean rendering of every template.
