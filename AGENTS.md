# TCF Bot Project Guide

This file is the top-level guide for agents and contributors working in this repository. It summarizes the current project layout, development commands, style rules, and safety requirements.

For user-facing setup, see [`README.md`](README.md). For current project state and improvement plan, see [`PLAN.md`](PLAN.md). For Replit deployment, see [`replit.md`](replit.md). For detailed developer documentation, see [`docs/README.md`](docs/README.md).

---

## Mandatory Read-Before-Work and Update-After-Work

Every new conversation in this repository must start by reading the canonical references and end by updating the related markdown. The user should NEVER need to remind you.

**Read at the start of every conversation:**

- [`agents/CLAUDE.md`](agents/CLAUDE.md) — canonical AI-agent reference
- [`agents/RULES.md`](agents/RULES.md) — hard constraints
- [`AGENTS.md`](AGENTS.md) (this file), [`PLAN.md`](PLAN.md), [`CHANGELOG.md`](CHANGELOG.md)
- The relevant subset of [`agents/`](agents/), [`agents/agents/`](agents/agents/), [`agents/skills/`](agents/skills/), [`docs/`](docs/), and project-root docs for the task

**Update in the same turn after every change:**

- [`CHANGELOG.md`](CHANGELOG.md) — entry under `[Unreleased]` (Added / Changed / Fixed / Removed / Documentation)
- [`PLAN.md`](PLAN.md) — when runtime, project state, priorities, or test counts change
- Every related `docs/*.md`, `agents/*.md`, [`README.md`](README.md), [`replit.md`](replit.md) whose content is now stale

See [`agents/CLAUDE.md`](agents/CLAUDE.md#mandatory-read-these-files-before-any-work) for the complete read/update tables. Skipping either step is a defect of the same severity as a failing test.

## Project Overview

TCF Bot is a Python Telegram bot for the Transsion Core Federation community. It manages federation-wide moderation actions, appeal workflows, staff roles, connected groups, audit logging, and health checks.

Current stack:

- Python 3.12 project target (`pyproject.toml` requires `>=3.12`)
- `python-telegram-bot[job-queue] == 22.5`
- MongoDB through Motor (`motor >= 3.7.1`)
- Flask keep-alive / health-check server
- `uv` for dependency management and lockfile-based installs
- Ruff for formatting and lint checks
- pytest + pytest-asyncio for offline tests

## Repository Layout

```text
tgbot/
├── tcbot/                    Main bot package
│   ├── __init__.py           Environment config loader and `cfg` adapter
│   ├── __main__.py           Runtime entry point, handler registration, polling
│   ├── alive.py              Flask keep-alive endpoint
│   ├── database/             MongoDB helpers, one file per collection/domain
│   ├── modules/              Telegram command modules and handlers
│   │   └── helper/           Shared helper code and conversation workflows
│   │       └── workflows/    ConversationHandler flows (`*_flow.py` only)
│   └── utils/                Logging, dispatch, prefixes, datetime helpers
├── tests/                    Offline pytest suite
├── docs/                     Developer documentation by subsystem
├── agents/                   Detailed coding, workflow, and style rules
├── config.env.example        Environment variable template
├── docker-compose.yml        Local bot + MongoDB compose setup
├── Dockerfile                Container image definition
├── pyproject.toml            Dependencies, pytest, and Ruff settings
├── uv.lock                   Locked dependency graph
├── README.md                 User-facing setup and architecture overview
├── PLAN.md                   Current project state and improvement plan
└── replit.md                 Replit deployment notes
```

Core ownership rules:

- Command handlers live in `tcbot/modules/`. See [`docs/modules/modules.md`](docs/modules/modules.md) for module boundaries.
- Shared handler helpers live in `tcbot/modules/helper/`. See [`docs/helper/helper.md`](docs/helper/helper.md) for helper docs.
- Conversation flows live in `tcbot/modules/helper/workflows/` and must be named `*_flow.py`. See [`docs/workflows/workflows.md`](docs/workflows/workflows.md) for conversation internals.
- MongoDB access lives in `tcbot/database/`; keep new database helpers in `*_db.py` files. See [`docs/databases/databases.md`](docs/databases/databases.md) for database layer notes.
- Runtime utilities live in `tcbot/utils/`. See [`docs/utils/utils.md`](docs/utils/utils.md) for utility docs.
- Tests live in `tests/` and should remain fully offline.

## Development Commands

Install dependencies from the lockfile:

```bash
uv sync --frozen
```

Install test extras when needed:

```bash
uv sync --extra test --frozen
```

Run the bot locally:

```bash
python3 -m tcbot
```

On Windows, use `python -m tcbot` if `python3` is not available.

Run tests:

```bash
python3 -m pytest tests/ -v
```

Equivalent with `uv` and test extras:

```bash
uv run --extra test pytest tests/ -v
```

Format and lint:

```bash
uv run ruff format .
uv run ruff check --fix .
```

Run with Docker Compose:

```bash
docker-compose up --build
```

## Configuration and Secrets

Configuration is loaded from environment variables. For local development, `python-dotenv` loads `config.env` when present. For Replit or hosted deployment, store secrets in the platform secret manager instead of committing them. See [`docs/setup.md`](docs/setup.md) for detailed setup instructions and [`replit.md`](replit.md) for Replit-specific notes.

Never commit real credentials. Required secret values include:

- `BOT_TOKEN` — Telegram bot token from BotFather.
- `MONGODB_URI` — MongoDB connection string.

Important non-secret/runtime variables include:

- `OWNER_ID` — initial federation founder Telegram user ID.
- `DB_NAME` — MongoDB database name, default `tcbot`.
- `COMMUNITY_NAME` — display name used in bot messages and logs.
- `PREFIXES` — command prefix list, default `['/', '!', '.']`.
- `PORT` — Flask keep-alive port, default `5000`; invalid or out-of-range values fall back to `5000`.
- `MAIN_GROUP`, `MAIN_CHANNEL`, `EXTEND_GROUP` — community chat IDs.
- `PROOFS`, `LOGS`, `LOGS_ERRORS`, `APPEALS` — log/proof/appeal destinations; values may be `chat_id` or `chat_id/thread_id`.
- `APPEAL_DISCUSSION_TOPIC` — thread ID in `MAIN_GROUP` for appeal review cards.
- `PROOF_TIMEOUT_SECONDS`, `APPEAL_TIMEOUT_SECONDS`, `ALBUM_DEBOUNCE_SECONDS` — conversation timing settings.
- `LOG_LEVEL` — bot log level.
- `MODULES_LOAD`, `MODULES_NO_LOAD` — optional module allowlist/denylist.

Use `config.env.example` as the complete template.

## Code Style and Naming

Follow the detailed rules in [`agents/CLAUDE.md`](agents/CLAUDE.md), [`agents/RULES.md`](agents/RULES.md), [`agents/STYLE-CODE.md`](agents/STYLE-CODE.md), and [`agents/STYLE-COMMENTS.md`](agents/STYLE-COMMENTS.md) before editing source code.

Repository conventions:

- Use Python 3.12 syntax and 4-space indentation.
- Place `from __future__ import annotations` as the first non-comment line in Python modules.
- Prefer built-in generics such as `list[str]`, `dict[str, int]`, and `int | None`.
- Avoid inline imports and wildcard imports.
- Use Ruff for formatting and import cleanup.
- Name async command handlers `cmd_*` and event handlers `on_*`.
- Name conversation states `WAITING_*`.
- Keep all bot messages HTML-only (`parse_mode='HTML'`) and escape user-provided text through the formatter helpers.
- Use `tcbot.utils.timedate_format` for UTC timestamps and display formatting.

## Architecture Rules

- `tcbot/__main__.py` builds the PTB application, starts Flask keep-alive, registers the global rate limiter, loads module handlers, and starts long polling.
- `tcbot/modules/__init__.py` discovers top-level module files, applies `MODULES_LOAD` / `MODULES_NO_LOAD` filters, and fails startup if an enabled module cannot be imported.
- Handlers should use database helper modules instead of calling `mongos.col()` directly.
- Multi-group actions should use `tcbot.utils.dispatch.fan_out()` to bound concurrent Telegram API calls.
- Role checks should use the canonical role helpers in `tcbot.database.users_db` and `tcbot.modules.helper.decorators.resolve_and_check`.
- Ban/kick flows must auto-demote users who currently hold a federation role.
- New conversation logic belongs in `tcbot/modules/helper/workflows/*_flow.py`.

## Testing Guidelines

The test suite is designed to run offline without a real Telegram token or MongoDB connection. Add or update tests when changing database helpers, handler behavior, workflow logic, formatting helpers, decorators, or utilities.

Current collected test inventory: 125 tests across 14 `tests/test_*.py` files.

Recommended validation after source changes:

```bash
uv run --extra test pytest tests/ -v
uv run ruff format .
uv run ruff check --fix .
```

For documentation-only changes, a test collection check is usually enough:

```bash
uv run --extra test pytest --collect-only -q
```

## Commit and Pull Request Guidance

For commit message conventions, see [`docs/git-commit.md`](docs/git-commit.md). For automated CI/CD and auto-PR workflows, see [`docs/workflows-guide.md`](docs/workflows-guide.md).

Use focused commits and conventional prefixes when appropriate:

- `feat:` for user-facing features
- `fix:` for bug fixes
- `refactor:` for behavior-preserving code changes
- `docs:` for documentation changes
- `test:` for test-only changes
- `chore:` for maintenance work

Pull requests should include:

- A short summary of the change.
- Test or validation commands run.
- Any configuration, database, or deployment impact.
- Screenshots or log excerpts only when user-visible behavior changed.

## Security Requirements

- Do not commit tokens, MongoDB URIs, API keys, passwords, or private chat IDs that should remain secret.
- Do not print or log secrets.
- Do not change `config.env` as part of normal code or documentation work.
- Keep database schema changes backward-compatible unless a migration plan is included.
- Update every read path if a stored MongoDB field is added, renamed, or removed.
