# TCF Bot Project Guide

This file is the top-level guide for agents and contributors working in this repository. It summarizes the current project layout, development commands, style rules, and safety requirements.

For user-facing setup, see [`README.md`](README.md). For contribution workflow,
see [`CONTRIBUTING.md`](CONTRIBUTING.md). For Replit deployment, see
[`replit.md`](replit.md). For detailed developer documentation, see
[`docs/README.md`](docs/README.md).

---

## Mandatory Read-Before-Work and Update-After-Work

Every new conversation in this repository must start by reading the canonical rules and end by updating the related markdown. The user should NEVER need to remind you.

**Read at the start of every conversation:**

- [`.agents/rules/tooling-validation.md`](.agents/rules/tooling-validation.md):
  workflow, dependency, documentation, and validation rules
- [`.agents/rules/code-style.md`](.agents/rules/code-style.md): Python style,
  architecture, handler, database, and async rules
- [`.agents/rules/comment-style.md`](.agents/rules/comment-style.md): comments,
  docstrings, section dividers, and Markdown rules
- [`AGENTS.md`](AGENTS.md) (this file), [`CHANGELOG.md`](CHANGELOG.md)
- The relevant [`.agents/skills/`](.agents/skills/), [`docs/`](docs/), and project-root docs for the task

**Update in the same turn after every change:**

- [`CHANGELOG.md`](CHANGELOG.md): entry under `[Unreleased]` (Added / Changed / Fixed / Removed / Documentation)
- Every related `docs/**/*.md`, `.agents/**/*.md`, [`README.md`](README.md), [`replit.md`](replit.md) whose content is now stale

See [`tooling-validation.md`](.agents/rules/tooling-validation.md#read-before-work-and-update-after-work)
for the complete read/update rules. Skipping either step is a serious defect.

## Skills and Sub-Agents Policy

**Skills in `.agents/skills/` auto-invoke whenever their trigger matches**: no need for the user to ask. If you are about to write code in `tcbot/`, invoke [`project-policy`](.agents/skills/project-policy/SKILL.md). If you are about to edit docs, invoke [`docs-maintainer`](.agents/skills/docs-maintainer/SKILL.md). Same for `mongodb-query-optimizer`, `async-python-patterns`, `python-code-quality`, `mermaid-diagrams`, `feature-reviewer`, `general-sub-agent`. Compose multiple skills when one task spans multiple areas.

## Autonomous Engineering Loop

For each improvement, update, fix, or audit, work through this bounded loop
autonomously:

1. **Scope** the concern and list the affected runtime, docs, configuration, and
   validation surfaces.
2. **Inspect** the canonical rules, current implementation, repository status,
   existing helpers, and possible duplicate or dead paths.
3. **Verify** version-sensitive library behavior with Context7 latest. Resolve
   the exact library before querying docs, use one concept per query, and never
   put credentials or private project data in a query.
4. **Design** the smallest modular change and centralize shared behavior in its
   owning helper or domain module. Do not create parallel utilities for logic
   that already has a project owner.
5. **Implement** focused typed Python 3.14 code with HTML-safe output,
   intentional comments, and explicit error handling.
6. **Validate** targeted behavior, the full relevant checks, startup logs for
   runtime changes, and stale/dead/duplicate paths.
7. **Review** every explicit requirement, synchronize related docs and
   changelog entries, and repeat only if a concrete defect remains. Stop when
   the checks are clean or report the exact blocker after bounded attempts.

Optimize for measured efficiency and bounded concurrency, not unverified
performance guarantees. Preserve correctness when ordering, dependencies,
authorization, or side effects require sequential execution.

## Project Overview

TCF Bot is a Python Telegram bot for the Transsion Core Federation community. It manages federation-wide moderation actions, appeal workflows, staff roles, connected groups, audit logging, and health checks.

Current stack:

- Python 3.14 project target (`pyproject.toml` requires `>=3.13`)
- `python-telegram-bot` (plain, no `[job-queue]` extra), tracking the latest compatible release
- MongoDB through Motor (latest)
- Flask keep-alive / health-check server
- `uv` for dependency management and lockfile-based installs
- Ruff for formatting and lint checks

## Repository Layout

```text
<project root>/
├── tcbot/                    Main bot package
│   ├── __init__.py           Environment config loader and `cfg` adapter
│   ├── __main__.py           Runtime entry point, handler registration, webhook/polling transport
│   ├── alive.py              Flask keep-alive and webhook receiver
│   ├── database/             MongoDB helpers, one file per collection/domain
│   │   ├── users_cache.py    Member profile cache operations
│   │   ├── users_roles.py    Role system: owners/admins/roles
│   │   ├── bans_db.py        Federation bans
│   │   ├── groups_db.py      Connected and pending groups
│   │   ├── warns_db.py       Warnings
│   │   ├── kicks_db.py       Kicks
│   │   ├── mutes_db.py       Mutes
│   │   ├── queues_db.py      Promotion requests
│   │   ├── cache.py          In-memory caches
│   │   ├── mongos.py         MongoDB client/indexes
│   │   ├── documents.py      Typed document shapes
│   │   └── types.py          Domain primitive types
│   ├── modules/              Telegram command modules and handlers
│   │   └── helper/           Shared helper code and conversation workflows
│   │       └── workflows/    ConversationHandler flows (`*_flow.py` only)
│   └── utils/                Logging, dispatch, prefixes, datetime helpers
├── docs/                     Developer documentation grouped by category
├── .agents/                   Coding skills and style rules
├── config.env.example        Environment variable template
├── docker-compose.yml        Local bot + MongoDB + Redis compose setup
├── Dockerfile                Container image definition
├── pyproject.toml            Dependencies and Ruff settings
├── uv.lock                   Locked dependency graph
├── CONTRIBUTING.md           Contribution workflow and review checklist
├── README.md                 User-facing setup and architecture overview
└── replit.md                 Replit deployment notes
```

Core ownership rules:

- Command handlers live in `tcbot/modules/`. See [`docs/architecture/modules.md`](docs/architecture/modules.md) for module boundaries.
- Shared handler helpers live in `tcbot/modules/helper/`. See [`docs/architecture/helpers.md`](docs/architecture/helpers.md) for helper docs.
- Conversation flows live in `tcbot/modules/helper/workflows/` and must be named `*_flow.py`. See [`docs/architecture/workflows.md`](docs/architecture/workflows.md) for conversation internals.
- MongoDB access lives in `tcbot/database/`; keep new database helpers in `*_db.py` files. See [`docs/architecture/database.md`](docs/architecture/database.md) for database layer notes.
- Runtime utilities live in `tcbot/utils/`. See [`docs/architecture/utilities.md`](docs/architecture/utilities.md) for utility docs.

## Development Commands

Install dependencies from the lockfile:

```bash
uv sync --frozen
```

Run the bot locally:

```bash
uv run python -m tcbot
```

Format and lint:

```bash
uv run ruff format .
uv run ruff check --fix .
```

Run with Docker Compose:

```bash
docker compose up --build
```

## Configuration and Secrets

Configuration is loaded from environment variables. For local development, `python-dotenv` loads `config.env` when present. For Replit or hosted deployment, store secrets in the platform secret manager instead of committing them. See [`docs/getting-started/setup.md`](docs/getting-started/setup.md) for detailed setup instructions and [`replit.md`](replit.md) for Replit-specific notes.

Never commit real credentials. Required secret values include:

- `BOT_TOKEN`: Telegram bot token from BotFather.
- `MONGODB_URI`: MongoDB connection string.

Important non-secret/runtime variables include:

- `OWNER_ID`: initial federation founder Telegram user ID.
- `DB_NAME`: MongoDB database name, default `tcbot`.
- `COMMUNITY_NAME`: display name used in bot messages and logs.
- `PREFIXES`: command prefix list, default `['/', '!', '.']`.
- `PORT`: Flask keep-alive port, default `5000`; invalid or out-of-range values fall back to `5000`.
- `MAIN_GROUP`, `MAIN_CHANNEL`, `EXTEND_GROUP`: community chat IDs.
- `PROOFS`, `LOGS`, `LOGS_ERRORS`, `APPEALS`: log/proof/appeal destinations; values may be `chat_id` or `chat_id/thread_id`.
- `APPEAL_DISCUSSION_TOPIC`: thread ID in `MAIN_GROUP` for appeal review cards.
- `PROOF_TIMEOUT_SECONDS`, `APPEAL_TIMEOUT_SECONDS`, `ALBUM_DEBOUNCE_SECONDS`: conversation timing settings.
- `LOG_LEVEL`: bot log level.
- `MODULES_LOAD`, `MODULES_NO_LOAD`: optional module allowlist/denylist.

Use `config.env.example` as the complete template.

## Code Style and Naming

Follow the detailed rules in
[`.agents/rules/tooling-validation.md`](.agents/rules/tooling-validation.md),
[`.agents/rules/code-style.md`](.agents/rules/code-style.md), and
[`.agents/rules/comment-style.md`](.agents/rules/comment-style.md) before
editing source code.

Repository conventions:

- Use Python 3.14 syntax and 4-space indentation.
- Place `from __future__ import annotations` as the first non-comment line in Python modules.
- Prefer built-in generics such as `list[str]`, `dict[str, int]`, and `int | None`.
- Avoid inline imports and wildcard imports.
- Use Ruff for formatting and import cleanup.
- Name async command handlers `cmd_*` and event handlers `on_*`.
- Name conversation states `WAITING_*`.
- Keep all bot messages HTML-only (`parse_mode='HTML'`) and escape user-provided text through the formatter helpers.
- Use `tcbot.utils.timedate_format` for UTC timestamps and display formatting.

## Architecture Rules

- `tcbot/__main__.py` builds the PTB application, starts Flask keep-alive, registers the global rate limiter, loads module handlers, and starts the native webhook transport when a public URL is available. Local development without a public URL falls back to polling.
- `tcbot/modules/__init__.py` discovers top-level module files, applies `MODULES_LOAD` / `MODULES_NO_LOAD` filters, and fails startup if an enabled module cannot be imported.
- Handlers should use database helper modules instead of calling `mongos.col()` directly.
- Multi-group actions should use `tcbot.utils.dispatch.fan_out()` to bound concurrent Telegram API calls.
- Role checks should use the canonical role helpers in `tcbot.database.users_roles` and `tcbot.modules.helper.decorators.resolve_and_check`.
- Ban/kick flows must auto-demote users who currently hold a federation role.
- New conversation logic belongs in `tcbot/modules/helper/workflows/*_flow.py`.

## Commit and Pull Request Guidance

For automated CI/CD and auto-PR workflows, see [`docs/operations/ci-cd.md`](docs/operations/ci-cd.md) for more details. Commit-specific instructions belong to the active repository workflow, not to the public `docs/` category.

Use focused commits and conventional prefixes when appropriate:

- `feat:` for user-facing features
- `fix:` for bug fixes
- `refactor:` for behavior-preserving code changes
- `docs:` for documentation changes
- `chore:` for maintenance work

Pull requests should include:

- A short summary of the change.
- For a long or detailed or short description submit to [`CHANGELOG.md`](CHANGELOG.md).
- Validation commands run (e.g. Ruff format and lint).
- Any configuration, database, or deployment impact.
- Screenshots or log excerpts only when user-visible behavior changed.

## Security Requirements

- Do not commit tokens, MongoDB URIs, API keys, passwords, or private chat IDs that should remain secret.
- Do not print or log secrets.
- Do not change `config.env` as part of normal code or documentation work.
- Keep database schema changes backward-compatible unless a migration plan is included.
- Update every read path if a stored MongoDB field is added, renamed, or removed.
