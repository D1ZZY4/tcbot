# Modules and Service Boundaries — TCF Bot

This document describes every module and helper package in the codebase — what it owns, what it exposes, and what it must never do.  
For architecture and startup flow, see [docs/architecture.md](architecture.md).  
For ConversationHandler patterns, see [docs/workflows.md](workflows.md).

---

## Module Discovery Rules

Modules are auto-discovered from `tcbot/modules/*.py` at import time by `modules/__init__.py`. A module is registered if:

1. It is not in the `MODULES_NO_LOAD` blacklist env var
2. It is in the `MODULES_LOAD` whitelist env var, or that whitelist is empty (load all)

Every module file must expose:

```python
__module_name__: str | None   # None hides from /help
__help_text__:   str          # required if __module_name__ is not None
__handlers__:    list         # list of PTB handlers
```

---

## Command Modules (`tcbot/modules/*.py`)

### `banning.py`

Federation ban entry point.

- Validates executor rank (requires developer or above)
- Checks if target holds a role → calls `auto_demote()` before the ban
- Writes target ID, reason, admin, and proof destination to `ctx.user_data`
- Returns `WAITING_PROOF` to start the ban proof ConversationHandler
- **Exposes:** `_BAN_CMDS`, `cmd_ban_start`, and `ban_conversation(cmd_ban_start, _BAN_CMDS)` in `__handlers__`
- **Delegates all proof collection to:** `ban_flow.ban_conversation()`

### `muting.py`

Mute and unmute commands.

- `cmd_mute_start` — validates rank (requires tester+), parses optional duration token, dispatches to `mute_conversation()`
- `cmd_unmute` — resolves target, applies unmute across all connected groups, logs result
- **Exposes:** `_MUTE_CMDS`, `_UNMUTE_CMDS`, `mute_conversation(cmd_mute_start, _MUTE_CMDS, escape_filter=_UNMUTE_CMDS)` + `MessageHandler` for unmute in `__handlers__`

### `kicking.py`

Kick command.

- `cmd_kick_start` — validates rank (tester+), calls `auto_demote()` if needed, delegates to `kick_conversation()`
- **Exposes:** `_KICK_CMDS` and `kick_conversation(cmd_kick_entry, _KICK_CMDS)` in `__handlers__`

### `warnings.py`

Warn, unwarn, warnlist, and resetwarns commands.

- `cmd_warn_start` — validates rank (tester+), delegates to `warn_conversation()`
- `cmd_unwarn` / `cmd_warnlist` / `cmd_resetwarns` — direct command handlers
- **Exposes:** `_WARN_CMDS`, `_WARN_ESCAPE_CMDS`, `warn_conversation(cmd_warn_entry, _WARN_CMDS, escape_filter=_WARN_ESCAPE_CMDS)` + `MessageHandler`s in `__handlers__`

### `appeals.py`

Appeal flow registration and pure guard functions.

- `starts_with_appeal_tag(text)` — pure: checks if text starts with `#appeal`
- `text_references_log_message(text, msg_id)` — pure: checks for log message ID in text
- `reviewer_locked_out(review_timestamp, ban_admin_id, reviewer_id)` — pure: 12-hour priority window logic (via `utc_now()` / `to_utc()`)
- **Exposes:** `_APPEAL_START_CMDS`, `appeal.build_handler(_APPEAL_START_CMDS)` + `CallbackQueryHandler(appeal.on_decision)` in `__handlers__`

### `unbanning.py`

Unban command.

- Validates rank (developer+)
- Resolves target by `ban_id` or `user_id`
- Delegates execution to `unban_flow.execute_unban()`
- **Exposes:** `MessageHandler` for `/tcunban` in `__handlers__`

### `admins.py`

Promote, demote, transfer-ownership, and promotion-queue commands.

- `cmd_promote` — calls `_execute_promote()` from `promote_flow.py`
- `cmd_demote` / `on_demote_confirm` / `on_demote_cancel` — confirm/cancel flow
- `cmd_transfer_owner` — founder-only ownership transfer
- `cmd_promote_requests` / `cmd_promote_list` — queue management (admin+)
- **Exposes:** multiple `MessageHandler`s and `CallbackQueryHandler`s in `__handlers__`

### `checking.py`

Ban status lookup commands (`/checkme`, `/baninfo`).

- Reference implementation for the role-aware response pattern
- `cmd_checkme` — user queries their own ban status
- `cmd_baninfo` — staff queries any user's ban status by ID or reply
- **Exposes:** `MessageHandler`s in `__handlers__`

### `connecting.py`

Group federation connect/disconnect management.

- `cmd_connect` — group owner requests connection
- `cmd_disconnect` — disconnect from federation
- All approval callbacks handled in `connected_flow.py`
- **Exposes:** handlers for connect, disconnect, and approval callbacks

### `stats.py`

Bot statistics commands.

- Aggregates ban counts, active groups, user counts, and staff list
- Delegates rendering to `stats_flow.py` and `stats_chats_flow.py`
- **Exposes:** `MessageHandler`s in `__handlers__`

### `start.py`

Bot PM entry and help menu.

- `/start` with a `appeal_<ban_id>` deep-link parameter → starts `appeal_flow`
- `/start` without parameter → shows main menu
- `/help` → shows module help index
- **Exposes:** `CommandHandler` + `CallbackQueryHandler`s in `__handlers__`

### `groups.py`

Connected groups listing and management commands.

- Lists all connected groups with group info
- **Exposes:** `MessageHandler` in `__handlers__`

---

## Helper Package (`tcbot/modules/helper/`)

These modules contain shared utilities used by command modules. They expose pure functions or factory functions. They do not expose PTB handlers.

### `decorators.py`

Auth decorators and cross-cutting concerns.

**Auth decorators** (used on command handlers):

| Decorator | Minimum role | Used for |
|---|---|---|
| `@owner_only` | founder (rank 4) | Ownership transfer, direct founder commands |
| `@staff_only` | admin (rank 3) | Promotion requests, staff lists |
| `@mod_only` | developer (rank 2) | Ban / unban |
| `@basic_mod_only` | tester (rank 1) | Kick / mute / warn |

**`@log_execution`** — opt-in tracer. Logs handler entry, exit, and elapsed ms at DEBUG level. Place innermost (closest to `async def`).

**`@ratelimiter(limit, period)`** — per-user sliding-window throttle using a `_RateLimiter` instance. Place outermost (evaluated first when the handler is called). Returns an appropriate error message to the user when the limit is exceeded.

### `extraction.py`

Target resolution for moderation commands.

**`extract_target(update, args, bot)`** → `(int | None, str | None)` (user_id, first_name)

Resolution order:
1. `args[0]` as numeric ID or `@username`
2. Reply-to-message sender
3. `text_mention` entity in the message
4. `@mention` entity resolved via `bot.get_chat()`

**`ResolvedTarget`** — named tuple `(user_id, first_name)` for passing resolved targets through context.

**`resolve_identity(user_id, bot)`** — resolves a user ID to a `(first_name, username)` pair; fills from `users_db` first, falls back to `bot.get_chat()`.

### `formatter.py`

HTML formatting helpers. All output is safe for `parse_mode="HTML"`.

| Function | Output |
|---|---|
| `esc(text)` | Escape `&`, `<`, `>` — use on ALL user-provided strings |
| `code(text)` | `<code>text</code>` |
| `mention(uid, fname)` | `<a href="tg://user?id=uid">fname</a>` |
| `bold(text)` | `<b>text</b>` |

### `keyboards.py`

All `InlineKeyboardMarkup` factory functions. See `agents/CLAUDE.md` for the canonical list. Never create keyboard functions in module files — always add to this file.

### `role_guard.py`

Shared role permission helpers for moderation flows.

**`resolve_and_check(msg, executor_id, target_id, *, min_role)`** → `(executor_role, target_role) | (None, None)`  
Resolves both roles, checks min_role for executor, checks executor > target rank. Replies with an appropriate error message on failure and returns `(None, None)`.

**`auto_demote(bot, target_id, target_fname, target_role, executor_id, executor_fname, action)`**  
Removes the target's role from DB, sends DM notification to target, posts log entry to log channel. Must be called before any ban or kick action when the target holds a role.

### `ban_info.py`

Shared ban rendering.

**`build_ban_detail(ban_doc, *, include_keyboard)`** → `(text: str, keyboard: InlineKeyboardMarkup | None)`  
Formats a ban document into an HTML summary with relevant links and optional inline keyboard. Used by `checking.py` and `stats.py` to avoid duplicating render logic.

### `parse_link.py`

Link builders and legacy datetime helper.

| Function | Purpose |
|---|---|
| `message_link(chat_id, msg_id)` | Builds `https://t.me/c/<link_id>/<msg_id>` |
| `appeal_deep_link(bot_username, ban_id)` | Builds `/start appeal_<ban_id>` deep link |
| `chat_id_to_link_id(chat_id)` | Converts `-100XXXXXXXXX` to `XXXXXXXXX` for link use |
| `user_link(uid, fname)` | HTML `<a>` mention (alias for `formatter.mention`) |
| `safe_first_name(fname)` | Escapes and truncates first name for safe HTML use |

### `parse_logmsg.py`

Log message text builders for role audit log entries.

| Function | Purpose |
|---|---|
| `role_assigned(...)` | "Role assigned: {role} → {user} by {admin}" |
| `role_removed(...)` | "Role removed: {role} from {user} by {admin}" |
| `role_auto_demoted(...)` | "Auto-demoted: {user} ({role}) — {action} by {admin}" |

### `parse_editmsg.py`

**`safe_edit(message, text, *, parse_mode, reply_markup)`**  
Edits a message and swallows `BadRequest: Message is not modified` errors. Used when a callback handler may try to edit a message that has not actually changed.

---

## Workflow Package (`tcbot/modules/helper/workflows/`)

These files contain `ConversationHandler` factories and executors. They do not define `__handlers__` or module-level command filters (`*_CMDS`) — those belong in the matching `tcbot/modules/*.py` file, following `admins.py`.

**Rule: there are no `*_conv.py` files.** All ConversationHandlers live in `*_flow.py`.

### `reason_flow.py`

Central reason-step infrastructure for kick, mute, and warn.

**Exports:**
- `WAITING_REASON = 0` and `WAITING_PROOF = 1` — state constants
- `parse_inline_reason(args, has_explicit_target)` → `str` — extracts inline reason from command args
- `BuildReason(action, *, skip_allowed, skip_label, cancel_label)` — configurable reason-step builder:
  - `.keyboard()` → `InlineKeyboardMarkup` — reason-step keyboard (Skip included only if `skip_allowed=True`)
  - `.prompt(target_mention, action_label, extra_info)` → `str` — "About to X Y. What's the reason?" prompt
- `build_modaction_conv(reason, proof, entry_fn, executor, entry_filter, escape_filter)` → `ConversationHandler`

All proof-step concerns live in `proof_flow.py`; `BuildProof` is imported from there.

### `ban_flow.py`

Album-aware ban proof ConversationHandler.

- **Module-level instance:** `proof = BuildProof("ban", skip_allowed=False)` — imported by `banning.py`
- State: `WAITING_PROOF`
- Buffers multiple photos/videos from a media album (album debounce window from `cfg.album_debounce`)
- On proof received: calls `_execute_ban()`, applies to all connected groups via `fan_out()`
- On `Cancel`: aborts the flow, edits the prompt
- **Factory:** `ban_conversation(entry_fn, entry_filter)` → `ConversationHandler`
- **Executor:** `_execute_ban(bot, msgs, meta)` — creates or updates the ban record, uploads proof, posts log

### `kicking_flow.py`

Kick executor and ConversationHandler.

- **Module-level instances:** `reason = BuildReason("kick")`, `proof = BuildProof("kick")` — imported by `kicking.py`
- `execute_kick(update, ctx, target_id, target_name, reason_text, proof_desc)` — ban + immediate unban in the current group
- `_exec_kick(update, ctx)` — adapter that pops `kick_*` keys from `user_data` and calls `execute_kick`
- **Factory:** `kick_conversation(entry_fn, entry_filter)` → delegates to `reason_flow.build_modaction_conv(reason, proof, ...)`

### `muting_flow.py`

Mute/unmute executors and ConversationHandler.

- **Module-level instances:** `reason = BuildReason("mute")`, `proof = BuildProof("mute")` — imported by `muting.py`
- `parse_duration(token)` → `timedelta | None` — parses `3d`, `1w`, `2h`, etc.
- `fmt_duration(td | None)` → `str` — formats duration for display
- `_execute_mute(bot, update, meta)` — applies restriction to all groups via `fan_out()`, edits the prompt to a summary
- `execute_unmute(update, ctx, target_id, fname)` — removes restriction from all groups
- `_exec_mute(update, ctx)` — adapter that copies `mute_*` keys from `user_data` and calls `_execute_mute`
- **Factory:** `mute_conversation(entry_fn, entry_filter, *, escape_filter=None)` → delegates to `reason_flow.build_modaction_conv(reason, proof, ...)`

### `warning_flow.py`

Warn executors and ConversationHandler.

- **Module-level instances:** `reason = BuildReason("warn", skip_allowed=False)`, `proof = BuildProof("warn")` — imported by `warnings.py`
- `execute_warn(update, ctx, target_id, target_name, reason_text, proof_desc)` — adds a warning in `warns_db`, auto-bans at `WARN_LIMIT`
- `execute_unwarn(update, ctx, target_id, target_name)` — removes the most recent warning
- `execute_warnlist(update, ctx, target_id, target_name)` — formats and sends a user's warning history
- `execute_resetwarns(update, ctx, target_id, target_name)` — clears all warnings for a user in the chat
- `_exec_warn(update, ctx)` — adapter that pops `warn_*` keys from `user_data` and calls `execute_warn`
- **Factory:** `warn_conversation(entry_fn, entry_filter, *, escape_filter=None)` → delegates to `reason_flow.build_modaction_conv(reason, proof, ...)`

### `unban_flow.py`

Unban executor. No ConversationHandler — unban is a single command.

- `execute_unban(update, ctx, target_id, target_fname)` — deactivates the ban in DB, unbans from all groups via `fan_out()`, posts log

### `appeal_flow.py`

Standalone appeal ConversationHandler. Entry via `/start appeal_<ban_id>` deep link.

- **Module-level instance:** `appeal = BuildAppeal(cfg.community_name, _LOG_CHANNEL_HANDLE)` — imported by `appeals.py`
- **`BuildAppeal(community_name, log_channel, *, cancel_label, cancel_callback)`** — configurable appeal flow builder:
  - `.instruction_text()` → `str` — multi-line HTML prompt shown when the user opens an appeal
  - `.cancel_keyboard()` → `InlineKeyboardMarkup` — single Cancel button for the instruction prompt
  - `.review_keyboard(ban_id)` → `InlineKeyboardMarkup` — Approve / Reject buttons for the staff review card
  - `.build_handler(entry_filter)` → `ConversationHandler` — assembles the full appeal conversation
  - `.on_decision(update, ctx)` — approve/reject callback registered outside the `ConversationHandler`
- State: `WAITING_APPEAL`
- Validates DM context, active ban ownership, and absence of a pending review
- Forwards the appeal text to `APPEALS` channel; posts review card to `APPEAL_DISCUSSION_TOPIC`

### `promote_flow.py`

Promote executor shared by `admins.py`.

- `_ROLE_ALIASES` — maps CLI arguments (`dev`, `developer`, `tester`, etc.) to canonical role strings
- `_available_roles_for(executor_role)` — returns the list of roles the executor may assign
- `_execute_promote(bot, executor_id, executor_fname, executor_role, target_id, target_fname, current_role, requested_role)` → `(bool, str)` — executes promotion or queues admin request; returns `(success, response_text)`

### `connected_flow.py`

Group connection flow — in-group join prompt, permission check, and pending monitoring.

- **Module-level instance:** `connection = BuildConnection(cfg.community_name)` — imported by `connecting.py`
- **`BuildConnection(community_name, *, required_perms, join_label, cancel_label, join_callback, cancel_callback)`** — configurable connection flow builder:
  - `.join_prompt()` → `str` — "Want to connect this group to X?" prompt
  - `.connected_message()` → `str` — success message edited into the prompt on completion
  - `.declined_message()` → `str` — shown when the owner cancels
  - `.already_connected_message()` → `str` — shown when the group is already in the federation
  - `.perms_required_message()` → `str` — shown when the bot lacks required admin permissions
  - `.join_keyboard()` → `InlineKeyboardMarkup` — Connect / Cancel inline keyboard
  - `.check_perms(member)` → `bool` — True if the bot holds all `required_perms`
  - `.complete_join(chat_id, title, owner_id, owner_fname, bot)` — connects the group, applies federation bans, posts log
  - `.on_bot_added(update, ctx)` — `my_chat_member` handler: detects add/remove, handles pending auto-join
  - `.on_join_decision(update, ctx)` — callback handler for Connect / Cancel buttons

### `stats_flow.py` / `stats_chats_flow.py`

Statistics executors. Pure async functions that query aggregation data and format it into HTML messages. No PTB handlers — called directly from `stats.py`.

### `proof_flow.py`

All proof-step concerns live here. Import proof helpers from this module — not from `reason_flow`.

**Exports:**
- `BuildProof(action, *, skip_allowed, skip_label, cancel_label)` — configurable proof-step builder:
  - `.keyboard()` → `InlineKeyboardMarkup` — proof-step keyboard (Skip included only if `skip_allowed=True`)
  - `.step_prompt(target_mention, action_label, reason, extra_info)` → `str` — "Reason noted — Xing Y" prompt (used after an in-conversation reason)
  - `.noted_prompt(action_label, inline_reason, target_mention, extra_info)` → `str` — "Xing Y. Reason: Z" prompt (used when reason was provided inline in the command)
  - `.record(msg)` → `str | None` — static; returns `"Photo (msg N)"` / `"Video (msg N)"` or `None`
- `upload_proof(bot, msgs, caption, proof_chat, proof_thread)` → `int | None` — uploads proof media (single or album) to the proof channel; returns the uploaded message ID or `None` on failure

---

## Database Package (`tcbot/database/`)

Each file owns exactly one MongoDB collection (or two for `admins_db.py` and `groups_db.py`). Module handlers must not call `col()` directly — always go through these helpers.

| File | Collections | Key exports |
|---|---|---|
| `mongos.py` | — | `connect()`, `ensure_indexes()`, `col(name)`, `make_short_id()` |
| `admins_db.py` | `tc_owners`, `tc_admins` | `is_owner`, `is_admin`, `is_staff`, `get_owner_id`, `add_admin`, `remove_admin`, `ensure_initial_owner`, `set_owner` |
| `bans_db.py` | `bans` | `get_active_ban`, `create_ban`, `update_ban`, `deactivate_ban`, `set_review`, `set_appeal_log_msg`, `active_ban_count`, `active_bans`, `active_ban_user_ids` |
| `groups_db.py` | `federated_groups`, `pending_joins` | `is_connected`, `add_group`, `deactivate_group`, `active_groups`, `active_group_count`, `add_pending`, `get_pending`, `remove_pending` |
| `roles_db.py` | `tc_roles` | `get_effective_role`, `role_rank`, `can_act_on`, `set_role`, `remove_role`, `get_role`, `ROLE_RANK`, `ROLE_LABEL`, `VALID_ROLES` |
| `users_db.py` | `member_cache` | `upsert_user`, `get_first_name` |
| `warns_db.py` | `warns` | `get_warns`, `add_warn`, `remove_warn`, `reset_warns` |
| `kicks_db.py` | `kicks` | `log_kick` |
| `mutes_db.py` | `mutes` | `log_mute` |
| `queues_db.py` | `promotion_requests` | `add_request`, `get_request`, `update_request_status`, `all_pending_requests` |
| `cache.py` | — | In-memory TTL caches: `effective_role_cache`, `connected_cache`, `active_groups_cache`, `owner_id_cache` |

---

## Utils Package (`tcbot/utils/`)

### `dispatch.py`

**`fan_out(coros, max_concurrent=10)`** → `list[Any | BaseException]`  
Executes a list of coroutines concurrently, bounded by a semaphore. Returns results in input order — each element is either the coroutine's return value or the captured exception. Never raises.

### `error_reporter.py`

Three-layer error classification and Telegram reporting.

- `attach(bot, chat_id, thread_id)` — installs the reporter onto the asyncio loop and PTB error handler
- `report_exc(exc, context_str)` — classifies, formats, and ships the error to the errors log channel

Error categories: `IGNORED` (expected API errors like `ChatMigrated`), `WARNING` (non-critical recoverable), `CRITICAL` (unexpected, full traceback).

### `logger.py`

**`BotLogFormatter`** — custom formatter: `[HH:MM] [DD-MM-YYYY] | community | L - module:line - msg`

**`setup(community_name, log_level)`** — installs `BotLogFormatter` on the root logger, caps third-party loggers.

### `prefixes.py`

**`build_prefixed_filters(command)`** → `filters.BaseFilter`  
Builds a combined `MessageFilter` that matches `/command`, `!command`, `.command`, and any other configured prefix from `PREFIXES` env var.

**`parse_cmd_args(text)`** → `list[str]`  
Strips the command prefix and returns the remaining tokens.

**`ALL_PREFIXES_CMD_FILTER`** — pre-built filter that matches any command with any configured prefix.

### `timedate_format.py`

Single source of truth for all datetime usage in the project.

| Function | Returns | Use when |
|---|---|---|
| `utc_now()` | tz-aware `datetime` | Storing timestamps in MongoDB, elapsed-time comparisons |
| `utcnow()` | naive UTC `datetime` | Building test fixtures or legacy naive timestamps |
| `to_utc(dt)` | tz-aware `datetime` | Normalizing naive or aware values before subtraction |
| `fmt_dt(dt)` | `str` | Displaying any datetime to users (`DD-MM-YYYY \| HH:MM`) |
| `utc_now_str()` | `str` | One-line formatted current time (`fmt_dt(utc_now())`) |

Never call `datetime.now(timezone.utc)` or `datetime.utcnow()` outside this module.
