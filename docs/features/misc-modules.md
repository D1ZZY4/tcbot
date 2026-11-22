# Miscellaneous modules

This page covers the command modules that are not part of moderation, roles,
language, or statistics. Each module owns its handlers and help entry where
applicable. The shared entry registration is described in
[modules](../architecture/modules.md).

Related pages: [flow overview](flow-overview.md) and
[helpers](../architecture/helpers.md).

## Start and main menu

`tcbot/modules/start.py` owns `/start` (alias none) and the main-menu callbacks.

- In groups it replies with a minimal message and a PM deep-link button.
- In private chat it shows the welcome panel with `main_menu_btn`, or dispatches
  the `about` argument.
- Appeal deep links of the form `/start appeal_<ref>` are handled by the appeal
  ConversationHandler, not here.
- `back_to_start`, `menu_groups`, `menu_groups_simple`, and
  `menu_groups_details` render the welcome and shared group panels. A failed
  group read shows an error and keeps the keyboard.

The command uses `ratelimiter(THROTTLE_READ)`; callbacks use
`THROTTLE_CALLBACK` and `log_execution`.

## Help

`tcbot/modules/help.py` owns `/help` and the help callbacks. `_builder_help(locale)`
imports every active module and calls `get_help(locale)`, skipping modules that
do not expose one. Topics, overviews, section labels, and keyboards are rebuilt
per request so they follow the tapper's locale. Section order and dynamic values
stay in Python; prose comes from the catalog.

Callbacks `help_menu`, `help_menu_group`, `helpc_main`, `help_topic`,
`help_section`, `helps_<topic>:<page>`, and `helpcs_<topic>:<page>` navigate the
menu. All use `THROTTLE_CALLBACK`.

## About, additional, and privacy

These are callback-only panels reached from the start menu.

| Module | Callback | Content |
|---|---|---|
| `about.py` | `about_menu` | Community description from `about_msg(locale)`. |
| `additional.py` | `additional_menu` | Official channels and groups; link buttons are built from configured destinations. |
| `privacy.py` | `privacy_menu`, `privacy_policy_menu`, `privacy_section_<n>` | Data-collection notice and six policy sections: collect, why, access, retention, rights, contact. |

All three use `answer_and_edit()` so the callback is acknowledged and the
message edited in parallel. A URL button is dropped when its resolved link is
empty.

## Greeting and join events

`tcbot/modules/greeting.py` is event driven and has no commands. It handles:

| Handler | Trigger | Behavior |
|---|---|---|
| `on_new_member` | `NEW_CHAT_MEMBERS` | Enforce active decisions in connected groups; greet only in the primary group. |
| `on_join_request` | `ChatJoinRequest` | Decline banned users; fail closed on a ban-read error. |
| `on_join_request_approved` | `CHAT_MEMBER` via approval | Re-apply a ban or mute. |
| `on_left_member` | `LEFT_CHAT_MEMBER` | Cleanup and notices. |
| `on_chat_migration` | `MIGRATE` | Repoint the chat id. |

Member processing harvests identity and reads the active ban and mute in
parallel under a global semaphore of 10. A cancelled read propagates; a failed
enforcement read suppresses the welcome. Join-time enforcement is detailed in
[connecting](moderation/connecting.md).

## Broadcast

`tcbot/modules/broadcast.py` owns `/tcbroadcast` (alias `/bc`), restricted to
staff with `ratelimiter(THROTTLE_FEDERATION)`. It sends a message to managed
groups through the bounded dispatch layer, records outcomes through the
broadcast tables, and posts a `messages.broadcast_log()` summary. Per-group
results are counted so one refusal does not abort the campaign.

## Maintenance

`tcbot/modules/maintenance.py` owns five operator commands:

| Command | Alias | Access | Purpose |
|---|---|---|---|
| `/tcleaveall` | `/leaveall`, `/exitall` | Owner (`THROTTLE_CRITICAL`) | Leave every managed group. |
| `/cleanup` | `/tcclean`, `/tcc` | Staff (`THROTTLE_FEDERATION`) | Remove stale groups after a membership probe. |
| `/tcrepair` | `/tcr` | Staff (`THROTTLE_FEDERATION`) | List unsettled enforcement runs and redrive failed targets. |
| `/tcforget` | `/tcf` | Owner (`THROTTLE_FEDERATION`) | Queue account erasure. |

`_leave_one()` stops the bot cleanly per chat. `_should_remove()` probes
membership before cleanup. `/tcrepair` uses `enforcement_db.list_unsettled_runs()`
and `redrive_run()` so a repair never files a second decision. Erasure is
queued through `erasure_db.request_erasure()` and drained by a scheduled job.

## Network tools

`tcbot/modules/netspeed.py` owns `/ping` (alias `/p`) and `/speedtest` (alias
`/st`), both Owner-only with `THROTTLE_FEDERATION`. They measure Telegram API
latency and network throughput and are intended for operator diagnostics on a
hosted runner. Results are logged and reported to the invoking Owner.

## Shared patterns

All modules above:

- resolve the locale once through `helper.locale`;
- send messages through the rich transport with no parse mode;
- build keyboards in `helper/buttons/`;
- read and write through `tcbot/database/` helpers;
- log through a module logger without secrets or private chat contents.

## Validation hints

Relevant tests include `tests/test_broadcasting.py`, `tests/test_netspeed.py`,
`tests/test_repair_command.py`, `tests/test_erasure_command.py`, and
`tests/test_startup_logging.py`.
