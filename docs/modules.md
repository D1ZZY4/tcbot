# Modules and Service Boundaries - TCF Bot

This page maps the module boundaries and service responsibilities used by the bot.
Before rewriting or refactoring modules, read the repository guidance in `agents/` for the expected code structure and naming conventions.
- `agents/RULES.md` - coding conventions, what is forbidden
- `agents/STYLE-CODE.md` - code style, typing, and formatting rules
- `agents/STYLE-COMMENTS.md` - comment and docstring style
- `agents/WORKFLOW.md` - branching, commit conventions, and deployment checklist
- `agents/CLAUDE.md` - project-specific guidance and gotchas
- `agents/REPLIT.md` - Replit environment, config, and secrets guidance

This document describes the high-level layout of service boundaries and module responsibilities.
It is based on the code under `tcbot/modules/`, `tcbot/database/`, and `tcbot/utils/`.

## Module discovery

Modules are discovered and filtered in `tcbot/modules/__init__.py`.
The `ALL_MODULES` list contains active modules after applying:

- `MODULES_LOAD` - explicit allow list
- `MODULES_NO_LOAD` - explicit deny list

The module loader imports each discovered module and collects `__handlers__` from each imported module.

## Module conventions

Each module file typically exposes:

- `__module_name__` - visible command name for `/help`
- `__help_text__` - short description of the module's functionality
- `__handlers__` - PTB handlers registered by the module

A module may hide itself from `/help` by setting `__module_name__ = None`.

The system loads handlers in priority order defined by `_PRIORITY_FIRST` and `_PRIORITY_LAST`.

## Command modules

`tcbot/modules/` contains the core command modules.
Examples include:

- `banning.py`
- `muting.py`
- `kicking.py`
- `warnings.py`
- `unbanning.py`
- `appeals.py`
- `connecting.py`
- `disconnecting.py`
- `maintenance.py`
- `help.py`
- `stats.py`
- `about.py`
- `privacy.py`
- `start.py`
- `greeting.py`

These modules implement Telegram commands and message handlers. Shared business logic is delegated to helper modules whenever possible.

Each command module follows this pattern:
1. Defines its entry-point function with auth and rate-limit decorators
2. Calls the relevant flow factory with its entry function
3. Exposes `__handlers__` directly at module level

## Helper subpackage

Shared helper behavior lives in `tcbot/modules/helper/`.
This package is the place for:

- keyboard builders (`keyboards.py`)
- HTML formatting helpers (`formatter.py` — `esc()`, `code()`, `mention()`, `bold()`)
- link and log message builders (`parse_link.py`, `parse_logmsg.py`)
- safe message edit helper (`parse_editmsg.py` — `safe_edit()` swallows stale-message errors)
- safety and filtering helpers (`decorators.py` — auth guards `owner_only` / `staff_only` / `mod_only` / `basic_mod_only`, the opt-in `log_execution` tracer, and `ratelimiter(limit, period)` per-user sliding-window rate limiter)
- role and authorization helpers (`role_guard.py` — `resolve_and_check()`, `auto_demote()`)
- ban presentation helpers (`ban_info.py` — `build_ban_detail()` shared between checking/stats)
- target extraction helpers (`extraction.py` — `extract_target()`, `resolve_identity()`)

The helper package also contains the `workflows/` subpackage.

## Workflow subpackage

Conversation and approval flows are organized under `tcbot/modules/helper/workflows/`.
**There are no `*_conv.py` files.** Every `ConversationHandler` is built inside a `*_flow.py`
file and exposed via a factory function.

### Central infrastructure

| File | Responsibility |
|---|---|
| `reason_flow.py` | `WAITING_REASON = 0`, `WAITING_PROOF = 1`, `build_modaction_conv()` — the single `ConversationHandler` factory for kick, mute, and warn; also exports keyboard builders, prompt helpers, `parse_inline_reason()`, and `record_proof()` |
| `proof_flow.py` | `upload_proof()` — media upload helper for the ban proof channel |

### Moderation flows

Each flow file owns executor logic, optional state handlers, and its factory function.

| File | Responsibility |
|---|---|
| `ban_flow.py` | `_execute_ban()`, album proof accumulators, `on_proof_received()`, `_flush_album()`, `on_cancel_proof()`, `ban_conversation(entry_fn)` |
| `kicking_flow.py` | `execute_kick()`, `_exec_kick()` adapter, `kick_conversation(entry_fn)` via `build_modaction_conv` |
| `muting_flow.py` | `parse_duration()`, `fmt_duration()`, `_execute_mute()`, `execute_unmute()`, `_exec_mute()` adapter, `mute_conversation(entry_fn)` via `build_modaction_conv` |
| `warning_flow.py` | `execute_warn/unwarn/warnlist/resetwarns()`, `_exec_warn()` adapter, `warn_conversation(entry_fn)` via `build_modaction_conv` |
| `unban_flow.py` | `execute_unban()` — DB deactivation, group unban, log dispatch (no `ConversationHandler` needed) |
| `appeal_flow.py` | Standalone appeal `ConversationHandler` with deep-link entry — independent of `reason_flow` |

### Standalone executors (no ConversationHandler)

| File | Responsibility |
|---|---|
| `connected_flow.py` | Group connection and disconnection flows |
| `promote_flow.py` | `_execute_promote()`, `_ROLE_ALIASES`, `_available_roles_for()` — shared by `admins.py` |
| `stats_flow.py` | Statistics executors |
| `stats_chats_flow.py` | Chat statistics executors |

See [Conversation flows and workflows](workflows.md) for more detail.

## Database boundaries

The database package abstracts MongoDB collections.
The codebase exposes a single `tcbot.database` namespace.

Each database module uses async helpers and provides a private `_col()` accessor:

- `admins_db.py`
- `bans_db.py`
- `groups_db.py`
- `roles_db.py`
- `users_db.py`
- `warns_db.py`
- `kicks_db.py`
- `mutes_db.py`
- `queues_db.py`

By convention, bot handlers do not call `col()` directly.

## Utilities

Utility modules support common concerns without owning bot actions:

- `tcbot/utils/logger.py`
- `tcbot/utils/prefixes.py`
- `tcbot/utils/dispatch.py` - `fan_out()` semaphore-bounded multi-group dispatcher (max 10 concurrent)
- `tcbot/utils/timedate_format.py`
- `tcbot/utils/error_reporter.py`

Use these modules for cross-cutting infrastructure such as logging, prefix parsing, fan-out dispatch, datetime formatting, and exception reporting.

## Related documentation

- [Documentation hub](index.md)
- [Project architecture](architecture.md)
- [Modules and service boundaries](modules.md)
- [Conversation flows and workflows](workflows.md)
- [Development workflow and onboarding](development.md)
- [AI / agent guidelines](agent-guidelines.md)
- [Agent instructions for Claude](../agents/CLAUDE.md)
- [Replit environment notes](../agents/REPLIT.md)
- [Code style guidelines](../agents/STYLE-CODE.md)
- [Comment style guidelines](../agents/STYLE-COMMENTS.md)
- [Workflow expectations](../agents/WORKFLOW.md)
- [Project rules and constraints](../agents/RULES.md)
