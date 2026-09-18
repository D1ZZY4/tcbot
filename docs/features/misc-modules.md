# Miscellaneous Modules

This document inventories the modules that do not have a dedicated feature
page: `start`, `about`, `additional`, `privacy`, `help`, `broadcasting`,
`greeting`, `maintenance`, `netspeed`, and `admins` (the promote/demote
flows themselves live in [`roles/roles.md`](roles/roles.md),
[`roles/promote.md`](roles/promote.md), and [`roles/demote.md`](roles/demote.md)).

For shared helpers used by these modules, see
[`../architecture/helpers.md`](../architecture/helpers.md). For the command
prefix system, see [`../architecture/modules.md`](../architecture/modules.md).
For the help index and runtime utilities, see
[`../architecture/utilities.md`](../architecture/utilities.md).

Stats and language have dedicated pages:
[`statistics.md`](statistics.md) and [`language.md`](language.md).

## Start: `start.py`

`/start` is the entry point for private chats and groups.

| Command | Aliases | Purpose | Access |
|---|---|---|---|
| `/start` | none | Show welcome menu in PM; show PM deep-link card in groups. | Anyone |

Behavior:

- PM context renders `main_menu_kb` (About, Help, Additional, Privacy,
  Language rows).
- Group / supergroup / forum context replies with a minimal card carrying
  `group_start_kb`: an "Open in PM" deep link (`https://t.me/<bot>?start=menu`)
  and a direct Help button (`help_menu_group`).
- `/start about` renders the about page without opening a conversation.
- `/start appeal_<id>` deep links are claimed by the appeal conversation
  handler in `appeals.py`, not by this module.
- Callbacks: `back_to_start` returns to the main menu; `menu_groups` /
  `menu_groups_simple` and `menu_groups_details` toggle the connected-groups
  list render (`groups_db.active_groups()`, simple vs fully detailed).

Rate limits: commands 8 per 30 s, callbacks 15 per 30 s.

Database impact: only reads `active_groups()` for the groups menu. A failed
read renders the load-failed card (never an empty list); an empty result
renders the "no groups connected" card; both keep the `back_to_start`
keyboard so re-tapping retries.

## About: `about.py`

No commands. A single callback renders the About page.

| Callback | Purpose |
|---|---|
| `about_menu` | Render the community description (from `about.toml`) with `back_to_start_kb`. |

Also reachable via `/start about`. Rate limit: 15 callbacks per 30 s.

## Additional: `additional.py`

No commands. A single callback renders the community links menu.

| Callback | Purpose |
|---|---|
| `additional_menu` | Render `additional.msg.body` with `additional_menu_kb`. |

`additional_menu_kb` includes a button row only when the matching env URL is
non-empty (`COMMUNITY_CHANNEL_URL`, `COMMUNITY_GROUP_URL`,
`COMMUNITY_LOGS_URL`, `COMMUNITY_EXEC_URL`, `COMMUNITY_TRAVEL_URL`); rows
with no configured URL are silently omitted. Rate limit: 15 callbacks per
30 s. No database impact.

## Privacy: `privacy.py`

No commands. Callback-only module rendering the data-collection notice and
the full privacy policy.

| Callback | Purpose |
|---|---|
| `privacy_menu` | Render the data-collection notice with `privacy_kb`. |
| `privacy_policy_menu` | Render the policy section index with `privacy_policy_sections_kb`. |
| `privacy_section_<idx>` | Render one policy section with `back_to_privacy_policy_kb`. |

Sections come from `_SECTION_KEYS` (`collect`, `why`, `access`, `retention`,
`rights`, `contact`) with labels/bodies read per locale at render time.
A callback with a non-numeric or out-of-range index (`idx < 0` or
`idx >= len(_SECTION_KEYS)`) is answered with an alert and does not touch
the message. Rate limit: 15 callbacks per 30 s. No database impact.

## Help: `help.py`

`/help` renders the in-bot help index built from every loaded module.

| Command | Aliases | Purpose | Access |
|---|---|---|---|
| `/help` | none | Show the help index; `/help <module>` opens a module. | Anyone |

| Callback | Purpose |
|---|---|
| `help_menu` / `help_menu_group` | Menu-path help index (start menu and group card link). |
| `helpc_main` | Command-path help index (from `/help`, no back-to-start). |
| `help_<mod>` / `helpc_<mod>` | Module overview (menu path / command path). |
| `helps_<mod>:<idx>` / `helpcs_<mod>:<idx>` | One section of a module overview. |

`_builder_help(locale)` collects `(name, overview, sections)` from every
module's `get_help(locale)`; non-help modules are skipped. Content is rebuilt
per request in the caller's locale (module-level `HELP_CONTENT` only caches
the default locale snapshot). Topics are sorted by display name; both the
module slug and the display name resolve `/help <module>` lookup. Rate
limits: commands 8 per 30 s, callbacks 15 per 30 s. No database impact.

## Broadcasting: `broadcasting.py`

| Command | Aliases | Purpose | Access |
|---|---|---|---|
| `/tcbroadcast` | `/bc` | Send text or forward a replied-to message to every active connected group. | Staff+ |

Behavior:

- Accepts inline text or a reply-to-forward; a command with neither replies
  with the no-content notice.
- Fans out one send per active group through `fan_out` (bounded, matches the
  dispatch cap), counting only transient errors as failures.
- Text sends use MarkdownV2; a `can't parse entities` `BadRequest` retries
  that group as plain text. Any other `BadRequest` re-raises so dead groups
  are not double-called.
- Posts `parse_logmsg.broadcast_log` (caller, preview, ok/failed counts) to
  `cfg.logs` and edits the status message in parallel.

Rate limit: 3 per 60 s, `@staff_only`.

Database impact: read-only (`groups_db.active_groups()`). A group-load
failure replies with the generic load-failed error and aborts.

## Greeting: `greeting.py`

No commands. This module enforces federation bans and mutes on member joins
and re-applies enforcement when join requests are approved.

| Handler | Trigger | Behavior |
|---|---|---|
| `on_new_member` | `NEW_CHAT_MEMBERS` | Enforces bans/mutes in every connected group; greets only in primary groups. |
| `on_join_request` | `ChatJoinRequest` | Declines the request silently when the requester has an active federation ban. |
| `on_join_request_approved` | chat member update with `via_join_request` | Re-applies active ban or mute when a join request is approved. |
| `on_left_member` | `LEFT_CHAT_MEMBER` | Announces non-bot member departures in primary groups only. |
| `on_chat_migration` | `MIGRATE` | Migrates group and warn records from the basic group to the supergroup. |

Key behavior:

- `_in_federation`: primary groups always qualify; other chats qualify only
  while their connected row is active (`is_connected`, L1+L2 cached). A
  lookup outage returns `None` so the caller stays silent instead of
  enforcing blind or greeting an unverified joiner.
- All concurrent join updates share one global `_join_sem`
  (`_MAX_CONCURRENT_JOINS = 10`) so a batch invite-link join cannot spike
  MongoDB pool pressure or Telegram traffic.
- `_handle_member` harvests identity and reads the active ban and mute in
  parallel. On an enforcement-read failure the welcome is skipped (fail
  closed: never greet an unverified user). A banned joiner is auto-demoted
  (`trigger="ban"`) and banned; a muted joiner is auto-demoted
  (`trigger="mute"`) and restricted to read-only for `until_date`. Primary
  groups post the removal notice (with ban ID and appeal deep link where
  applicable); secondary groups enforce silently.
- `on_join_request_approved` uses `via_join_request` so the same join is
  never double-enforced by `on_new_member`. It also re-checks the ban
  because a ban created after the request decline (or a failed decline) must
  still be enforced.

Database impact: `users_cache.harvest_user_identity` (opportunistic, skips
the write on unchanged identity), reads `bans_db.get_active_ban` and
`mutes_db.get_active_mute`, and on migration `groups_db.migrate_group` plus
`warns_db.migrate_records`.

## Maintenance: `maintenance.py`

| Command | Aliases | Purpose | Access |
|---|---|---|---|
| `/leaveall` | `/exitall`, `/tcleave` | Leave every non-primary connected group and mark them inactive. | Founder only |
| `/cleanup` | `/tcclean`, `/tcc` | Check active groups and deactivate ones the bot can no longer access. | Staff+ |

Behavior:

- Primary groups (`main_group`, `exec_group`) are never touched by either
  command; they are guarded at every call site by `cfg.is_primary_group`.
- `/leaveall` is rate limited to 1 per 300 s and runs bounded per-group
  leave + deactivate. A group counts as failed when either the leave or the
  deactivate fails (a successful `leave_chat` with a failed deactivate would
  leave a "ghost" active row).
- `/cleanup` is rate limited to 3 per 60 s and uses bounded membership
  checks with `_MEMBERSHIP_CHECK_TIMEOUT = 3.0` per check.

Database impact: `/leaveall` deactivates each `federated_groups` row in
parallel with the leave and posts a `group_disconnected` log entry per
group to `cfg.logs` (a leave counts as failed unless both `leave_chat` and
`deactivate_group` succeed). `/cleanup` deactivates rows whose membership
check reports the bot as `left` or `kicked`; a failed membership check
keeps the group (fail closed).

## Netspeed: `netspeed.py`

| Command | Aliases | Purpose | Access |
|---|---|---|---|
| `/ping` | `/p` | Telegram API round-trip latency in ms. | Founder only |
| `/speedtest` | `/st` | Full Ookla speed test (download, upload, ping, client/server details). | Founder only |

Behavior:

- `/ping` replies "Pinging…", measures the elapsed time, and edits the
  message to the latency (single round-trip read).
- `/speedtest` replies "Running…", runs the Ookla test in an executor thread
  bounded by `_SPEEDTEST_TIMEOUT = 180` s, and edits the result. Timeouts and
  unparseable results (missing keys or `None` where a mapping was expected)
  edit a dedicated notice instead of raising. A non-http(s) share URL is
  logged and sent without the photo.

Rate limit: 3 per 60 s for both commands, `@owner_only`. No database impact.

## Admin module surface: `admins.py`

The admin module owns the role-management command surface; the flows are
documented in [`roles/roles.md`](roles/roles.md), [`roles/promote.md`](roles/promote.md),
and [`roles/demote.md`](roles/demote.md).

| Command | Aliases | Purpose | Access |
|---|---|---|---|
| `/tcpromote` | `/tcp` | Assign a federation role (or queue Founders-only promotions). | Staff+ |
| `/tcdemote` | `/tcd` | Remove a federation role with a confirm/cancel prompt. | Staff+ |
| `/transferowner` | `/tfowner` | Transfer Founder ownership. | Founder only |
| `/tcpromoterequests` | `/tcreqs` | Submit a promotion request with proof. | Anyone |
| `/tcpromotelist` | `/tcplist` | List pending promotion requests. | Staff+ |

| Callback | Purpose |
|---|---|
| `promo_approve:<request_id>` / `promo_reject:<request_id>` | Founder verdict on a pending promotion request (DM card). |
| `promo_role:<role>:<target_id>` | Choose a role in the `/tcpromote` inline menu. |
| `promo_role_cancel:<target_id>` | Cancel the role-selection menu. |
| `demote_confirm:<target_id>` / `demote_cancel:<target_id>` | Confirm or cancel a demotion. |

Rate limits: promote/demote/list queries 5 per 60 s; transfer and promote
requests 3 per 300 s; role and decision callbacks 10 per 30 s.

Database impact: `users_roles` (promote/demote), `queues_db` (promotion
requests), and `users_cache` on transfer; see the role docs for details.

## Shared module conventions

- Permission gates come from `decorators` (`staff_only`, `owner_only`,
  `mod_only`, `basic_mod_only`) and fail closed on role-lookup outages.
- Every handler wears `@decorators.log_execution` for DEBUG entry/exit
  traces and a `@decorators.ratelimiter` quota; the Founder bypasses
  per-handler quotas.
- Callback handlers pair `q.answer()` with `safe_edit_cb` / `answer_and_edit`
  so re-tapping the same view does not raise `Message is not modified`.
- All user-facing prose renders MarkdownV2 through the formatter helpers and
  the locale engine (`helper.locale.locale_for_update`).
