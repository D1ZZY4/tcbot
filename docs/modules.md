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

## Helper subpackage

Shared helper behavior lives in `tcbot/modules/helper/`.
This package is the place for:

- keyboard builders (`keyboards.py`)
- formatting helpers (`formatter.py`, `parse_logmsg.py`, `parse_link.py`)
- safety and filtering helpers (`decorators.py` — auth guards `owner_only` / `staff_only` / `mod_only` / `basic_mod_only`, the opt-in `log_execution` tracer, and `ratelimiter(limit, period)` per-user sliding-window rate limiter; `parse_editmsg.py` — safe message edit with content-unchanged guard)
- role and authorization helpers (`role_guard.py`)
- ban presentation helpers (`ban_info.py`)
- target extraction helpers (`extraction.py`)

The helper package also contains the `workflows/` subpackage.

## Workflow subpackage

Conversation and approval flows are organized under `tcbot/modules/helper/workflows/`.
Each workflow is split into two concerns:

- `*_flow.py` - execution logic for the feature
- `*_conv.py` - Telegram `ConversationHandler` builder and state definitions

Example pairs:

- `ban_flow.py` / `ban_conv.py`
- `proof_flow.py` / `proof_conv.py`
- `muting_flow.py` / `muting_conv.py`
- `unban_flow.py` / `unban_conv.py`
- `kicking_flow.py` / `kicking_conv.py` (ConversationHandler factory; entry point passed in from `kicking.py`)
- `warning_flow.py` / `warning_conv.py`
- `appeal_flow.py` (no conv pairing — external deep-link flow)

Standalone executors (no ConversationHandler): `connected_flow.py`, `stats_flow.py`, `stats_chats_flow.py`, `promote_flow.py`.

Shared reason utilities: `reason_flow.py` — `parse_inline_reason()`, `reason_prompt()`, `reason_noted_prompt()` reused by kick, mute, and warn entry points.

`promote_flow.py` contains the shared `_execute_promote` executor used by `admins.py` and its callbacks. It lives in `workflows/` alongside the other execution flows.

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
- `tcbot/utils/dispatch.py` - `fan_out()` semaphore-bounded multi-group dispatcher
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
