# TCF Bot — Planning and Project State

This document tracks how TCF Bot currently runs, what is considered stable, and what should be improved next. Keep it practical: record current behavior, known risks, and validation commands rather than aspirational placeholders.

## Current Project State

| Area | Status |
|---|---|
| Runtime | Long-polling Telegram bot started with `python3 -m tcbot`. |
| Python target | Python 3.12 project target (`pyproject.toml` requires `>=3.12`). |
| Bot framework | `python-telegram-bot[job-queue] == 22.5`. |
| Database | MongoDB through Motor, connected during PTB `post_init`. |
| Health check | Flask app in `tcbot/alive.py`, `GET /` returns `OK` on `PORT` (default `5000`). |
| Dependency management | `uv` with `uv.lock`. |
| Formatting/linting | Ruff, configured in `pyproject.toml`. |
| Tests | 134 collected tests across 14 `tests/test_*.py` files; designed to run offline. |
| Deployment notes | Local `config.env`, Docker Compose, and Replit/hosted environment variables are documented. |

## Runtime Flow

### Startup Sequence

```text
python3 -m tcbot
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

1. `connect()` creates the Motor client and verifies MongoDB with `ping`.
2. `ensure_indexes()` creates required MongoDB indexes in parallel.
3. `ensure_initial_owner(cfg.initial_owner_id)` seeds the first owner when needed.
4. `error_reporter.attach(...)` stores the bot and error destination for async reports.
5. The asyncio loop exception handler is registered.

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

`tcbot/modules/__init__.py` discovers top-level `*.py` files in `tcbot/modules/`, excludes `__init__.py`, applies the optional `MODULES_LOAD` allowlist and `MODULES_NO_LOAD` denylist, imports active modules, and collects their `__handlers__` lists.

### Database Layer

All database operations are async and should go through helper modules in `tcbot/database/`.

Current collection/domain owners include:

| Collection/domain | Helper |
|---|---|
| Federation bans | `bans_db.py` |
| Owners/admins | `admins_db.py` |
| Developer/tester roles | `roles_db.py` |
| Connected and pending groups | `groups_db.py` |
| Member profile cache | `users_db.py` |
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

- Use canonical role helpers from `tcbot.database.roles_db` and `tcbot.modules.helper.role_guard`.
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
| `stats_flow.py`, `stats_chats_flow.py` | Stats display flows. |

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
python3 -m tcbot
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

### P0 — Critical

No active P0 items are documented in this file.

### P1 — High

| Item | Area | Status | Notes |
|---|---|---|---|
| Verify full suite on every source change | Tests | Ongoing | Use `uv run --extra test pytest tests/ -v`. |
| Keep docs aligned with env/config changes | Documentation | Ongoing | Update `README.md`, `AGENTS.md`, `PLAN.md`, and `replit.md` when runtime setup changes. |

### P2 — Medium

| Item | Area | Status | Notes |
|---|---|---|---|
| Expand edge-case workflow tests | Tests | Open | Appeal, ban proof album buffering, and timeout paths are good candidates. |
| Review deployment-specific port assumptions | Deployment | Open | Runtime defaults to `PORT=5000`; hosts may require a different value. |

### P3 — Low

| Item | Area | Status | Notes |
|---|---|---|---|
| Keep documentation links current | Documentation | Ongoing | Prefer project-relative links that exist in the repository. |

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

Result: 134 tests collected across 14 test files.
