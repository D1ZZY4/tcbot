# Project Architecture - TCF Bot

This document explains the repository architecture and runtime shape.
Before altering architecture-related code, review the repository guidance in `agents/` to ensure the change matches style, workflow, and environment rules.
- `agents/RULES.md` - coding conventions, what is forbidden
- `agents/STYLE-CODE.md` - code style, typing, and formatting rules
- `agents/STYLE-COMMENTS.md` - comment and docstring style
- `agents/WORKFLOW.md` - branching, commit conventions, and deployment checklist
- `agents/CLAUDE.md` - project-specific guidance and gotchas
- `agents/REPLIT.md` - Replit environment, config, and secrets guidance

This document describes the code architecture for the TCF bot repository.
It is based on the code under `tcbot/` and the test suite in `tests/`.

## Core package

The application lives under `tcbot/`.
The primary packages are:

- `tcbot/__init__.py` - configuration parsing and the central `cfg` adapter
- `tcbot/__main__.py` - bot startup, handler registration, error handling, and keepalive
- `tcbot/alive.py` - Flask keepalive server on port `5000`
- `tcbot/database/` - async MongoDB helpers and collection access
- `tcbot/modules/` - Telegram command modules, helper utilities, and workflow builders
- `tcbot/utils/` - logging, prefix parsing, error reporting, and date formatting

This repository is a Telegram bot, not a web service. The bot uses long polling via `python-telegram-bot`.

## Startup flow

1. `python3 -m tcbot` starts `tcbot.__main__.main()`.
2. `setup_logging()` configures structured logs.
3. `start_keepalive()` starts the Flask health-check thread.
4. `ApplicationBuilder()` builds the Telegram application and registers handlers from `tcbot.modules.get_handlers()`.
5. `app.run_polling()` begins message polling.

The startup path also attaches a multi-layer error strategy:

- Layer 1: global rate limiter via `global_rate_limit_handler`
- Layer 2: PTB error handler `_error_handler` that reports unhandled exceptions
- Layer 3: asyncio exception handler for task-level failures

## Configuration

Configuration is loaded from `config.env` through `tcbot/__init__.py`.
The configuration object is immutable via `Configs` and exposed through `cfg`.

Key config values:

- `BOT_TOKEN`
- `OWNER_ID`
- `MONGODB_URI`
- `DB_NAME`
- `COMMUNITY_NAME`
- `LOGS`, `LOGS_ERRORS`, `PROOFS`, `APPEALS`, `MAIN_GROUP`
- `PROOF_TIMEOUT_SECONDS`, `APPEAL_TIMEOUT_SECONDS`
- `MODULES_LOAD`, `MODULES_NO_LOAD`

See [Development workflow and onboarding](development.md) for configuration guidance.

## Database layer

The async database packages are under `tcbot/database/`.
The public database namespace is `tcbot.database` via `tcbot/database/__init__.py`.

Important files:

- `tcbot/database/mongos.py` - Motor client, `connect()`, `ensure_indexes()`, and `col()` accessors
- `tcbot/database/admins_db.py` - owner and admin CRUD
- `tcbot/database/bans_db.py` - federation bans, active ban queries, and enforcement helpers
- `tcbot/database/groups_db.py` - group connection state and pending join queue
- `tcbot/database/roles_db.py` - role resolution, rank checks, and role-based authorization
- `tcbot/database/users_db.py` - member caching and name resolution
- `tcbot/database/kicks_db.py`, `mutes_db.py`, `warns_db.py`, `queues_db.py`

The project enforces async database helpers only. Handlers use the database layer rather than raw collection calls.

## Module and handler model

Module discovery is implemented in `tcbot/modules/__init__.py`.
The system loads active modules from the directory, applies `MODULES_LOAD` and `MODULES_NO_LOAD`, and respects priority ordering.

Each module file may expose:

- `__module_name__`
- `__help_text__`
- `__handlers__`

Handlers are registered in a deterministic order:
- `connecting`, `admins`, `appeals`, `banning`, `muting`, `kicking`, `warnings`
- then normal modules
- then `about`, `privacy`, `start`, `greeting`

See [Modules and service boundaries](modules.md) for details.

## Helper subpackage and workflows

Shared utilities live under `tcbot/modules/helper/`.
This package contains:

- `formatter.py` - HTML text builders and safe formatting helpers
- `extraction.py` - target resolution and identity helpers
- `keyboards.py` - inline keyboard builders
- `decorators.py` - access control decorators (`owner_only`, `staff_only`, `mod_only`, `basic_mod_only`), the opt-in `log_execution` tracing decorator, and `ratelimiter(limit, period)` per-user sliding-window throttle
- `role_guard.py` - shared role enforcement logic and auto-demotion
- `parse_link.py` / `parse_logmsg.py` / `parse_editmsg.py` - message formatting and safe edit helpers
- `ban_info.py` - shared ban detail rendering
- `workflows/` - conversation handler flows and executors

See [Conversation flows and workflows](workflows.md) for the workflow structure.

## Utility helpers

The `tcbot/utils/` package provides support functions used across the bot.
Key modules:

- `logger.py` - structured logging setup and formatting
- `prefixes.py` - command and prefix parsing helpers
- `dispatch.py` - `fan_out()` semaphore-bounded multi-group dispatcher (max 10 concurrent)
- `timedate_format.py` - timezone-aware formatting and UTC helpers
- `error_reporter.py` - error delivery for uncaught exceptions

## Testing and verification

The repository includes an offline test suite under `tests/`.
Run:

```bash
python3 -m pytest tests/ -q
```

For bot startup verification, use `python3 -m tcbot`.

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
