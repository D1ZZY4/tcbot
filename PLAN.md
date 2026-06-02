# TCF Bot: Planning and Project State

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
| Tests | 332 collected tests across 26 `tests/test_*.py` files; designed to run offline. All green on 2026-06-02. |
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
| `stats_flow.py` | Unified `Stats` class covering overview, staff roster, users, chats, bans, and search. |

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

1. **Correctness and safety:** preserve federation moderation behavior, secrets safety, and database compatibility.
2. **Offline test coverage:** keep tests independent of Telegram and MongoDB services.
3. **Clear module boundaries:** handlers call helpers; database writes stay in `tcbot/database/`; shared flows stay in `workflows/`.
4. **Operational visibility:** errors and important moderation events should be logged to configured destinations.
5. **Performance:** use bounded fan-out for group-wide operations and avoid sequential I/O where safe.

## Current Priority Backlog

> The backlog below was re-verified line by line against the source tree on
> 2026-06-01. Each prior entry was checked against the actual code rather than
> trusted from a previous review pass. The disposition of every prior claim is
> recorded under "Backlog Review" so the audit trail stays clear.

### Backlog Review (2026-06-01)

#### Resolved in this pass

- **Authorization test coverage.** Added `tests/test_users_roles.py` (14 tests)
  covering role-rank ordering, owner/admin/role CRUD, effective-role resolution,
  and role-cache invalidation. Extended `tests/test_decorators.py` (10 → 19
  tests) to cover the authorization guards `owner_only`, `staff_only`,
  `mod_only`, `basic_mod_only`, and `resolve_and_check`. MongoDB is replaced with
  in-memory fakes so both suites stay offline and deterministic. Full suite is
  now 148 tests across 15 files.

#### Dismissed after verification (no action required)

- **"Missing Telegram API timeouts."** Already implemented. `extraction.py:24-30`
  (`_safe_get_chat`) wraps every `bot.get_chat()` call in
  `asyncio.wait_for(timeout=3.0)`; the previously proposed fix already exists in
  the code.
- **"Missing bot token validation."** `tcbot/__init__.py:188` calls
  `_required_env("BOT_TOKEN")`, which already enforces presence with a clear
  startup error. Only token *format* validation is absent, and that is tracked as
  optional hardening under P3.
- **"Missing MongoDB URI validation."** `MONGODB_URI` presence is enforced via
  `_required_env` at `tcbot/__init__.py:189`. The cited `tcbot/__main__.py:128-130`
  does not handle the URI at all (it calls `connect()` / `ensure_indexes()`).
  Only URI *format* validation is absent, and that is tracked as optional
  hardening under P3.
- **"Missing composite indexes for `$in` queries."** The unique `user_id` index
  on `member_cache` (`mongos.py:126`) already serves the `$in` batch lookups in
  `users_cache.py`. A composite index would only enable a covered query, which is
  a marginal optimization rather than a correctness or hot-path issue. Tracked
  under P3.
- **"`ctx.user_data` used as long-term state."** This is the idiomatic
  python-telegram-bot per-conversation store. Usages are transient and explicitly
  cleared (`.pop(...)`) after each flow step, so this is not a defect.
- **"Conversation flow classes lack docstrings."** Every flow class already has a
  class-level docstring (`BuildAppeal`, `Check`, `BuildConnection`, `Demote`,
  `Promote`, `BuildProof`, `BuildReason`, `Stats`). Only some method docstrings
  are missing, and those are tracked under P2.

### P1: High (Before Next Release)

| # | Issue | Location | Fix |
|--|--|--|--|
| 1 | No entry-to-completion ConversationHandler state-machine tests | `tcbot/modules/helper/workflows/*.py` | Resolved 2026-06-02: ban flow (8 tests), warning flow (12 tests), appeal flow (17 tests, new file). All step handlers covered: entry, validation guards, cancel, timeout, proof receipt, message submission, and approve/reject decisions. | Resolved |

### P2: Medium (Documentation and Coverage)

| # | Issue | Location | Fix | Status |
|--|--|--|--|--|
| 1 | Method-level docstrings incomplete on flow classes | `tcbot/modules/helper/workflows/*.py` | Verified 2026-06-02: all flow class methods already have docstrings. | Resolved |
| 2 | Remaining workflow files undocumented | `docs/workflows/workflows.md` | Verified 2026-06-02: all 12 flows are documented. | Resolved |

### P3: Low (Optional hardening, nice to have)

| # | Item | Notes |
|--|--|--|
| 1 | ~~`BOT_TOKEN` format validation~~ | `_warn_bot_token_fmt` added to `tcbot/__init__.py`; logs WARNING on bad format. 13 new tests. Resolved 2026-06-02. |
| 2 | ~~`MONGODB_URI` format validation~~ | `_warn_mongodb_uri_fmt` added to `tcbot/__init__.py`; logs WARNING on bad prefix. Resolved 2026-06-02. |
| 3 | ~~Covered-query composite index on `member_cache`~~ | `{user_id: 1, first_name: 1, username: 1}` index added to `mongos.ensure_indexes()`. Resolved 2026-06-02. |
| 4 | Shared module-interface types (`tcbot/modules/types.py`) | Only if module-to-module signatures grow ambiguous. |
| 5 | Query metrics collection / docstring-format standardization | Data-driven tuning and documentation consistency. |



## Code Review Findings

Use this section to keep code review findings in one consistent place. It applies
to anyone reviewing this codebase. After a review, add each finding as a row in the
table for its priority tier, where P1 is the highest and P5 is the lowest.
Confirmed and prioritized items move up into the
[Current Priority Backlog](#current-priority-backlog) above. Cleared items are set
to `Dismissed` with the reason written in the Evidence column. The italic rows are
placeholders that show the expected format, so replace them and do not leave them
in.

### How to record a finding

- One finding per row, specific and self-contained.
- **Location** must be a real `file.py:line` you actually opened, never a guess.
- **Evidence** must quote the relevant code or describe the behavior you observed
  that proves the finding is real. A finding with no evidence counts as unverified.
- **Verify first.** Open the cited file and confirm the issue is not already
  handled before listing it. In the 2026-06-01 review, several findings flagged as
  critical turned out to be already implemented in the code.
- **Do not overstate severity.** Already-validated input, idiomatic framework
  usage, and marginal micro-optimizations are not P1 or P2.
- **Status** uses the values below. Use `Resolved` only when a fix has landed and
  tests pass. Use `Dismissed` (with a reason) when verification shows the finding
  is not a real issue.

**Status values:**

- `Open`: logged, not started.
- `Verified`: confirmed against the code.
- `In Progress`: being worked on.
- `Resolved`: fixed and tests pass.
- `Dismissed`: checked and not a real issue, with the reason in Evidence.

**Priority tiers:**

- **P1 (Critical):** security holes, data loss, crashes, or broken core moderation; fix before the next release.
- **P2 (High):** incorrect behavior or untested critical logic such as auth and federation actions.
- **P3 (Medium):** maintainability, partial test coverage, and non-hot-path performance.
- **P4 (Low):** documentation gaps, minor cleanups, and naming.
- **P5 (Optional / Future):** speculative or nice-to-have ideas; gather evidence before promoting them.

### P1 (Critical)

| # | Finding | Location (`file.py:line`) | Evidence (code quote / observed behavior) | Proposed Fix | Status |
|--|--|--|--|--|--|
| 1 | `_paginate`, `_nav_row`, `_date` undefined at runtime in `stats_flow.py` | `tcbot/modules/helper/workflows/stats_flow.py:1` | All twelve call sites used private names (`_paginate`, `_nav_row`, `_date`) that were never defined in the module; calling any Stats drill-down raised `NameError` immediately | Replace all call sites with `paginate(..., _PAGE_SIZE)`, `nav_row(...)`, `date_or_unknown(...)` imported from `tcbot.utils.pagination` | `Resolved` |
| 2 | `_paginate`, `_nav_row`, `_date` undefined at runtime in `check_flow.py` | `tcbot/modules/helper/workflows/check_flow.py:1` | Same root cause as stats_flow: twelve call sites used stale private names leftover from before pagination was extracted to utils; any Check drill-down raised `NameError` | Add `from tcbot.utils.pagination import date_or_unknown, nav_row, paginate` and replace all twelve call sites | `Resolved` |
| 3 | `_kb` undefined at runtime in `tcbot/modules/groups.py` | `tcbot/modules/groups.py:85,103` | `_kb(False)` and `_kb(detailed)` called but never defined; `/tcgroups` and Detail/Simple toggle both raised `NameError` immediately | Imported `tcgroups_kb` from `tcbot.modules.helper.keyboards` and replaced both `_kb(...)` call sites | `Resolved` |

### P2 (High)

| # | Finding | Location (`file.py:line`) | Evidence (code quote / observed behavior) | Proposed Fix | Status |
|--|--|--|--|--|--|
| 1 | `check_flow.py` had zero test coverage | `tests/` (file absent) | No `tests/test_check_flow.py` existed; all `Check` class view builders (`profile`, `bans_list`, `ban_detail`, `warns_by_group`, `warns_in_group`, `kicks_list`, `mutes_list`, `appeals_list`) were untested | Add `tests/test_check_flow.py` with offline monkeypatched tests for every public method | `Resolved` |

### P3 (Medium)

| # | Finding | Location (`file.py:line`) | Evidence (code quote / observed behavior) | Proposed Fix | Status |
|--|--|--|--|--|--|
| 1 | `uv run ruff` documented throughout `.agents/` but silently failed on Replit | `.agents/STYLE-CODE.md:17`, `.agents/TEST-RUFF.md:53` | `uv run ruff format .` exited with code 1 because ruff was in `[project.optional-dependencies.dev]`, which `uv run` does not install by default | Moved ruff to `[dependency-groups] dev = ["ruff"]` in `pyproject.toml`; `uv sync` now installs it automatically; `uv run ruff check .` and `uv run ruff format .` both pass clean | `Resolved` |

### P4 (Low)

| # | Finding | Location (`file.py:line`) | Evidence (code quote / observed behavior) | Proposed Fix | Status |
|--|--|--|--|--|--|
| 1 | Stale test count in docs (300/25 instead of 319/26) | `README.md:180`, `AGENTS.md:192`, `replit.md:117`, `PLAN.md:21` | After adding `test_check_flow.py` (19 tests), all four docs still referenced the old "300 tests across 25 files" baseline | Update all four docs to "319 tests across 26 files" | `Resolved` |

### P5 (Optional / Future)

| # | Finding | Location (`file.py:line`) | Evidence (code quote / observed behavior) | Proposed Fix | Status |
|--|--|--|--|--|--|
| 1 | `member_cache` batch queries could benefit from a covered composite index | `tcbot/database/mongos.py:1` | `get_first_names_batch` issues `$in` on `user_id` with a `first_name` projection; existing `user_id` index is not covering | `{user_id: 1, first_name: 1, username: 1}` index added to `ensure_indexes()` on 2026-06-02; batch `$in` projections are now covered queries. | `Resolved` |

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

Result: 176 tests collected across 18 test files.
