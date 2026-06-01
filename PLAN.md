# TCF Bot — Planning and Project State

This document tracks how TCF Bot currently runs, what is considered stable, and what should be improved next. Keep it practical: record current behavior, known risks, and validation commands rather than aspirational placeholders.

For user-facing overview, see [`README.md`](README.md). For contributor rules and style, see [`AGENTS.md`](AGENTS.md). For deployment notes, see [`replit.md`](replit.md). For developer documentation, see [`docs/README.md`](docs/README.md). For CI/CD automation details, see [`docs/workflows-guide.md`](docs/workflows-guide.md). For changelog of recent changes, see [`CHANGELOG.md`](CHANGELOG.md).

## Current Project State

| Area | Status |
|---|---|
| Runtime | Long-polling Telegram bot started with `uv run python -m tcbot`. |
| Python target | Python 3.12 project target (`pyproject.toml` requires `>=3.12`). |
| Bot framework | `python-telegram-bot[job-queue] == 22.5`. |
| Database | MongoDB through Motor, connected during PTB `post_init`. |
| Health check | Flask app in `tcbot/alive.py`, `GET /` returns `OK` on `PORT` (default `5000`). |
| Dependency management | `uv` with `uv.lock`; CI installs with frozen lockfile by default. |
| Formatting/linting | Ruff, configured in `pyproject.toml`. |
| Tests | 125 collected tests across 14 `tests/test_*.py` files; designed to run offline. |
| Deployment notes | Local `config.env`, Docker Compose, and Replit/hosted environment variables are documented. |

## Runtime Flow

### Startup Sequence

```text
uv run python -m tcbot
  │
  ├── tcbot/__init__.py
  │     Loads environment variables.
  │     Loads local config.env through python-dotenv when present.
  │     Builds immutable Configs dataclass.
  │     Exposes cfg adapter used by the rest of the project.
  │
  └── tcbot/__main__.py: main()
        ├── setup_logging(level=cfg.log_level)
        ├── start_keepalive()
        │     Starts Flask in a daemon thread on 0.0.0.0:cfg.port.
        │
        ├── ApplicationBuilder()
        │     token(cfg.bot_token)
        │     post_init(_post_init)
        │     concurrent_updates(True)
        │     connection_pool_size(8)
        │     get_updates_connection_pool_size(4)
        │     read/write/connect/pool timeouts
        │
        ├── Handler registration
        │     group -1: TypeHandler(Update, global_rate_limit_handler)
        │     group  0: handlers discovered from tcbot/modules/*.py
        │     group 10: member-cache update for non-command group text
        │     errors: _error_handler
        │
        └── run_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)
```

### `post_init` Sequence

`_post_init(app)` runs after the PTB application is built and before polling starts:

1. Required env vars are parsed before startup; `BOT_TOKEN`, `MONGODB_URI`, and `OWNER_ID` must be present.
2. Enabled modules are imported during handler collection; import failures stop startup instead of silently skipping handlers.
3. `connect()` creates the Motor client and verifies MongoDB with `ping`.
4. `ensure_indexes()` creates required MongoDB indexes in parallel.
5. `ensure_initial_owner(cfg.initial_owner_id)` seeds the first owner when needed.
6. `error_reporter.attach(...)` stores the bot and error destination for async reports.
7. The asyncio loop exception handler is registered.

### Request Processing Pipeline

```text
Telegram update
  │
  ├── group -1: global per-user rate limiter
  │     Callback queries and commands are throttled before module handlers.
  │
  ├── group 0: command/module handlers
  │     Modules are dynamically discovered from tcbot/modules/*.py.
  │     Handlers apply auth decorators and per-handler rate limits where needed.
  │
  └── group 10: member cache updater
        Stores user profile snapshots for text messages in connected groups.
```

## Architecture Summary

### Main Package Boundaries

| Path | Responsibility |
|---|---|
| `tcbot/__init__.py` | Environment parsing, `Configs`, and the global `cfg` adapter. |
| `tcbot/__main__.py` | Application startup, handler registration, MongoDB startup, polling, error handling. |
| `tcbot/alive.py` | Flask health-check server. |
| `tcbot/modules/` | Command modules and Telegram handlers. |
| `tcbot/modules/helper/` | Shared formatter, keyboard, decorator, target extraction, and role guard helpers. |
| `tcbot/modules/helper/workflows/` | ConversationHandler flows, all named `*_flow.py`. |
| `tcbot/database/` | Async MongoDB access helpers and document/type definitions. |
| `tcbot/utils/` | Logging, bounded fan-out dispatch, prefix filters, datetime helpers, error reporting. |
| `tests/` | Offline pytest suite. |

### Module Discovery

`tcbot/modules/__init__.py` discovers top-level `*.py` files in `tcbot/modules/`, excludes `__init__.py`, applies the optional `MODULES_LOAD` allowlist and `MODULES_NO_LOAD` denylist, imports active modules, and collects their `__handlers__` lists. If any enabled module fails to import, startup now exits with the failing module names so a partially registered bot is not deployed.

### Database Layer

All database operations are async and should go through helper modules in `tcbot/database/`.

Current collection/domain owners include:

| Collection/domain | Helper |
|---|---|
| Federation bans | `bans_db.py` |
| Connected and pending groups | `groups_db.py` |
| Member profile cache | `users_cache.py` |
| Owners/admins + dev/tester roles | `users_roles.py` |
| Warnings | `warns_db.py` |
| Kicks | `kicks_db.py` |
| Mutes | `mutes_db.py` |
| Promotion requests | `queues_db.py` |
| MongoDB client/indexes | `mongos.py` |
| In-memory caches | `cache.py` |
| Typed document shapes | `documents.py` |
| Domain primitive types | `types.py` |

### Error Handling

| Layer | Location | Purpose |
|---|---|---|
| PTB error handler | `app.add_error_handler(_error_handler)` | Reports unhandled handler exceptions. |
| Asyncio exception handler | `loop.set_exception_handler(...)` | Reports background task failures. |
| Logging integration | `tcbot/utils/error_reporter.py` | Sends formatted error details to the configured destination. |

## Role System Summary

Role hierarchy:

1. Founder
2. Admin
3. Developer
4. Tester

Important rules:

- Use canonical role helpers from `tcbot.database.users_roles` and `tcbot.modules.helper.decorators.resolve_and_check`.
- Do not duplicate manual role-check chains in handlers.
- Ban and kick flows must auto-demote targets that currently hold a federation role.
- Promotion and demotion workflows should preserve auditability through logs and queue records.

## Conversation Flow Summary

Conversation flows live in `tcbot/modules/helper/workflows/` and use `ConversationHandler` where needed.

Primary flows:

| Flow | Purpose |
|---|---|
| `ban_flow.py` | Ban proof collection, album buffering, and federation ban execution. |
| `appeal_flow.py` | Private appeal submission and staff decision handling. |
| `connected_flow.py` | Group join approval and connection checks. |
| `reason_flow.py` | Shared reason/proof steps for moderation actions. |
| `proof_flow.py` | Proof upload helpers and prompts. |
| `kicking_flow.py`, `muting_flow.py`, `warning_flow.py`, `unban_flow.py` | Action-specific moderation workflows. |
| `promote_flow.py` | Role promotion execution helpers. |
| `stats_flow.py` | Unified `Stats` class — overview, staff roster, users, chats, bans, search. |

For detailed behavior, see `docs/workflows/workflows.md`.

## Development and Validation Commands

Install dependencies:

```bash
uv sync
```

Install test extras:

```bash
uv sync --extra test
```

Run the bot:

```bash
uv run python -m tcbot
```

Run tests:

```bash
uv run --extra test pytest tests/ -v
```

Collect tests only:

```bash
uv run --extra test pytest --collect-only -q
```

Format and lint:

```bash
uv run ruff format .
uv run ruff check --fix .
```

Run local bot + MongoDB:

```bash
docker-compose up --build
```

## Improvement Strategy

Priorities, in order:

1. **Correctness and safety** — preserve federation moderation behavior, secrets safety, and database compatibility.
2. **Offline test coverage** — keep tests independent of Telegram and MongoDB services.
3. **Clear module boundaries** — handlers call helpers; database writes stay in `tcbot/database/`; shared flows stay in `workflows/`.
4. **Operational visibility** — errors and important moderation events should be logged to configured destinations.
5. **Performance** — use bounded fan-out for group-wide operations and avoid sequential I/O where safe.

## Current Priority Backlog

### P0 — Critical (Must Fix Before Next Release)

| # | Security/Performance Issue | Location | Fix | Priority |
|--|--|--|--|----------|
| 1 | Missing bot token validation at startup | `tcbot/__init__.py:188` | Add explicit token format validation with clear error message | CRITICAL - Prevents runtime authentication failures |
| 2 | No MongoDB URI validation | `tcbot/__main__.py:128-130` | Add URI format validation before connection attempt | HIGH - Prevents information disclosure |
| 3 | Missing timeouts on Telegram API calls | `tcbot/modules/helper/extraction.py:97-100` | Add `asyncio.wait_for(timeout=3.0)` to all `get_chat()` calls | HIGH - Prevents 30s+ hangs |
| 4 | Missing composite indexes for $in queries | `users_cache.py:78-84`, `users_cache.py:108-111` | Add composite indexes `{user_id: 1, first_name: 1, username: 1}` | HIGH - 50-100ms improvement per batch query |

### P1 — High (Before Next Release)

| # | Test Coverage/Integration Issue | Location | Fix | Priority |
|--|--|--|--|----------|
| 1 | No tests for users_roles.py | `tcbot/database/users_roles.py` | Add fixtures for tc_owners, tc_admins, tc_roles collections | CRITICAL - Core authorization logic untested |
| 2 | No tests for auth decorators | `tcbot/modules/helper/decorators.py` | Create mock Update objects for testing | CRITICAL - Security logic untested |
| 3 | No tests for complete workflows | `tcbot/modules/helper/workflows/*.py` | Test full conversation flows from entry to completion | HIGH - Critical user flows untested |
| 4 | ctx.user_data used as long-term state | Across all modules | Move to proper ConversationHandler state or dedicated cache module | HIGH - Prevents state leakage, improves testability |
| 5 | No shared type definitions for module interfaces | `tcbot/modules/**/*.py` | Create `tcbot/modules/types.py` for all module-to-module interfaces | MEDIUM - Eliminates ambiguity in function signatures |

### P2 — Medium (Next Release)

| # | Documentation Issue | Location | Fix | Priority |
|--|--|--|--|----------|
| 1 | Add docstrings to conversation flow classes | `tcbot/modules/helper/workflows/*.py` | Add docstrings to all class methods | MEDIUM - Better API documentation |
| 2 | Document remaining workflow files | `tcbot/modules/helper/workflows/*.py` | Add mermaid diagrams and detailed documentation | MEDIUM - Complete workflow documentation |

### P3 — Low (Future)

| # | Nice to Have | Priority |
|--|--|----------|
| 1 | Add query metrics collection | LOW - Enables data-driven tuning |
| 2 | Standardize docstring format | LOW - Documentation consistency |



## Maintenance Rules

- Do not commit real secrets or private chat IDs.
- Do not edit `config.env` for normal documentation or code changes.
- Do not add dependencies manually to a requirements file; use `uv` and `pyproject.toml`.
- Keep database schema changes backward-compatible unless a migration plan is included.
- Keep bot messages HTML-only and escape user-provided text through formatter helpers.
- Keep conversation files named `*_flow.py`.
- Keep tests offline and deterministic.

## Recent Documentation Baseline

This documentation pass updates the root Markdown files to reflect the current project stack, runtime flow, configuration model, test inventory, and deployment guidance:

- `AGENTS.md`
- `README.md`
- `PLAN.md`
- `replit.md`

Validation used for this baseline:

```bash
uv run --extra test pytest --collect-only -q
```

Result: 125 tests collected across 14 test files.
