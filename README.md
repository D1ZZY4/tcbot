# TCF Bot

TCF Bot is a Telegram federation management bot for the Transsion Core Federation community. It coordinates moderation across connected groups, records audit trails, supports appeal review, and exposes a small Flask health-check endpoint for hosted environments.

## Features

- **Federation bans**: create, update, and lift bans across all connected groups.
- **Ban proof workflow**: collect proof media/text before enforcement and store proof message references.
- **Appeals**: deep-link private-message flow with staff review buttons and appeal records.
- **Connected groups**: approve group joins, track active groups, and run multi-group actions safely.
- **Staff roles**: Founder, Admin, Developer, and Tester hierarchy with promotion/demotion workflows.
- **Moderation actions**: ban, unban, kick, mute, warn, warning reset, checks, stats, and broadcast helpers.
- **Smart mentions**: global username-based mentions with automatic fallback to plain text + ID for users without usernames.
- **Flexible target resolution**: reply-first priority with partial name search support for natural command usage.
- **Audit logging**: moderation, appeal, role, and error reports to configured log destinations.
- **Health checks**: Flask keep-alive server on `PORT` with `GET /` returning `OK`.

## Stack

| Component | Current project setting |
|---|---|
| Python | 3.12 project target (`requires-python = ">=3.12"`) |
| Bot framework | `python-telegram-bot` (with the `[job-queue]` extra), tracking the latest compatible release |
| Database | MongoDB through Motor (latest) |
| Health server | Flask (latest) |
| Configuration | Environment variables, with `python-dotenv` loading local `config.env` |
| Dependency manager | `uv` with `uv.lock` |
| Formatting/linting | Ruff |

## Quick Start

### 1. Install dependencies

```bash
uv sync
```

### 2. Configure environment

For local development, copy the template and fill in your own values:

```bash
cp config.env.example config.env
```

Never commit real credentials. At minimum, the bot needs:

- `BOT_TOKEN`: Telegram bot token from BotFather.
- `MONGODB_URI`: MongoDB connection string.
- `OWNER_ID`: Telegram user ID for the initial federation founder.

See [Configuration](#configuration) below and `config.env.example` for the complete list. For detailed setup instructions, see [`docs/setup.md`](docs/setup.md). For Replit-specific setup, see [`replit.md`](replit.md).

### 3. Run the bot

```bash
uv run python -m tcbot
```

## Docker Compose

```bash
docker-compose up --build
```

The compose setup starts the bot and a local `mongo:7` service. The bot reads `config.env` and waits for MongoDB to pass its health check.

See [`docs/setup.md`](docs/setup.md) for detailed Docker setup instructions.

## Replit / Hosted Deployment

Use Replit Secrets or the hosting platform's secret manager for credentials. Do not store tokens or MongoDB URIs in committed files.

Recommended run command:

```bash
uv run python -m tcbot
```

The Flask keep-alive server binds to `0.0.0.0:${PORT}`. If `PORT` is unset, invalid, or outside `1..65535`, the application defaults to `5000`.

See [`replit.md`](replit.md) for Replit-specific setup notes and deployment checklist.

## Configuration

Configuration is loaded from environment variables in `tcbot/__init__.py`. For local development, `python-dotenv` reads `config.env` if it exists. Startup fails fast when required runtime values such as `BOT_TOKEN`, `MONGODB_URI`, or `OWNER_ID` are missing.

For detailed environment variable formats and validation, see [`docs/setup.md`](docs/setup.md). For Replit-specific deployment, see [`replit.md`](replit.md).

| Variable | Required | Description |
|---|---:|---|
| `BOT_TOKEN` | Yes | Telegram bot token from BotFather. |
| `OWNER_ID` | Yes | Positive Telegram user ID seeded as the initial Founder. |
| `MONGODB_URI` | Yes | MongoDB connection string. |
| `DB_NAME` | No | MongoDB database name, default `tcbot`. |
| `COMMUNITY_NAME` | No | Display name used in bot messages and logs. |
| `PREFIXES` | No | Python-style list of command prefixes, default `["/", "!", "."]`. |
| `PORT` | No | Flask keep-alive port, default `5000`; invalid or out-of-range values fall back to `5000`. |
| `MAIN_GROUP` | Usually | Main community group/forum chat ID. Required for appeal review cards and promotion-flow messages. |
| `MAIN_CHANNEL` | No | Main announcement channel chat ID. |
| `EXTEND_GROUP` | No | Optional secondary/staff group watched by selected handlers. |
| `PROOFS` | Usually | Proof destination as `chat_id` or `chat_id/thread_id`. |
| `LOGS` | Usually | Action log destination as `chat_id` or `chat_id/thread_id`. |
| `LOGS_ERRORS` | No | Error log destination; if empty, code paths may use the parsed empty value. |
| `APPEALS` | Usually | Appeal record destination as `chat_id` or `chat_id/thread_id`. |
| `APPEAL_LOG_HANDLE` | No | Public log handle shown in appeal instructions. |
| `APPEAL_DISCUSSION_TOPIC` | Usually | Thread ID inside `MAIN_GROUP` for appeal review cards. |
| `PROOF_TIMEOUT_SECONDS` | No | Ban proof conversation timeout, default `100`; values below `1` fall back to default. |
| `APPEAL_TIMEOUT_SECONDS` | No | Appeal DM conversation timeout, default `600`; values below `1` fall back to default. |
| `ALBUM_DEBOUNCE_SECONDS` | No | Album media grouping window, default `2`; values below `1` fall back to default. |
| `LOG_LEVEL` | No | Logging level, default `INFO`. |
| `MODULES_LOAD` | No | Comma-separated module allowlist. |
| `MODULES_NO_LOAD` | No | Comma-separated module denylist. |

Destination variables such as `LOGS`, `PROOFS`, and `APPEALS` accept either a chat ID (`-1001234567890`) or a forum topic pair (`-1001234567890/42`).

## Architecture Summary

```mermaid
flowchart TD
    Updates[Telegram updates] --> App[PTB application in tcbot.__main__]
    App --> RateLimit[Global rate limiter group -1]
    RateLimit --> Modules[Dynamic command modules tcbot.modules]
    Modules --> Helpers[Shared helpers and workflows]
    Helpers --> DbHelpers[Database helper modules]
    DbHelpers --> Mongo[(MongoDB via Motor)]
```

Key runtime pieces:

- `tcbot/__init__.py` loads environment configuration into an immutable dataclass and exposes the `cfg` adapter.
- `tcbot/__main__.py` starts logging, launches Flask keep-alive, builds the PTB application, registers handlers, connects MongoDB in `post_init`, and starts long polling.
- `tcbot/modules/__init__.py` discovers top-level modules, collects their `__handlers__` lists, and fails startup if an enabled module cannot be imported.
- `tcbot/database/mongos.py` owns the Motor client, database accessor, short ID generator, and index setup.
- `tcbot/utils/dispatch.py` provides bounded concurrent fan-out for multi-group Telegram API calls.
- `tcbot/utils/error_reporter.py` receives handler, asyncio, and logging errors for reporting to the configured error destination.

For detailed architecture, see [`docs/mapping.md`](docs/mapping.md) and [`PLAN.md`](PLAN.md). For module breakdown, see [`docs/modules/modules.md`](docs/modules/modules.md). For database details, see [`docs/databases/databases.md`](docs/databases/databases.md).

## Repository Layout

```text
tgbot/
├── tcbot/                    Bot package
│   ├── database/             Async MongoDB helper modules
│   ├── modules/              Command modules and Telegram handlers
│   │   └── helper/           Formatters, decorators, keyboards, workflows
│   │       └── workflows/    Conversation flows (`*_flow.py`)
│   └── utils/                Logging, prefixes, dispatch, datetime helpers
├── docs/                     Developer subsystem documentation
├── .agents/                   Detailed agent and contributor rules
├── config.env.example        Environment template
├── docker-compose.yml        Bot + MongoDB local compose setup
├── pyproject.toml            Project metadata, dependencies, Ruff
├── uv.lock                   Locked dependency graph
├── AGENTS.md                 Project guide for .agents/contributors
├── PLAN.md                   Current project state and improvement plan
└── replit.md                 Replit deployment notes
```

## Code Quality

```bash
uv run ruff format .
uv run ruff check --fix .
```

Ruff targets Python 3.12 and line length 88. GitHub Actions install dependencies through `uv sync --frozen` so CI follows `pyproject.toml` and `uv.lock`. Project code should follow the detailed rules in [`.agents/CLAUDE.md`](.agents/CLAUDE.md), [`.agents/RULES.md`](.agents/RULES.md), [`.agents/STYLE-CODE.md`](.agents/STYLE-CODE.md), and [`.agents/STYLE-COMMENTS.md`](.agents/STYLE-COMMENTS.md).

## CI/CD & Automation

The project uses **4 automated GitHub Actions workflows** for continuous integration, code quality, and maintenance:

### Auto-Fix Code Quality
**File:** `.github/workflows/auto-fix.yml`

Automatically fixes code style and linting issues with Ruff:
- Runs on push to `main`, `feat/**`, `fix/**` branches
- Runs on pull requests and weekly (Monday 04:00 UTC)
- **Creates PR with fixes** for review before merge
- **Never commits directly to main** - always requires review
- Zero manual intervention for code style

### Dependency Updates (Like Dependabot)
**File:** `.github/workflows/dependency-update.yml`

Weekly automated dependency updates:
- Runs every Monday 04:00 UTC
- Executes `uv lock --upgrade` to update all dependencies
- **Auto-creates PR** with the updated lockfile
- **Telegram notifications** with results
- Zero manual work for routine updates

### Other Workflows
- **CodeQL** (`.github/workflows/codeql.yml`) - Security analysis
- **Run Bot** (`.github/workflows/run-bot.yml`) - Self-chaining 24/7 long-polling runner. Each run polls for a ~5 hour window (GitHub caps a job at 6h), then dispatches its successor ~15 minutes before the window ends for continuous coverage. A `concurrency` group keeps a single instance polling (a second would hit Telegram's `409 Conflict`), and an every-30-minute cron acts as a resurrection fallback.

### Full Documentation
For detailed workflow descriptions, trigger conditions, notification format examples, troubleshooting, and best practices, see [`docs/workflows-guide.md`](docs/workflows-guide.md). For changelog of all CI/CD additions, see [`CHANGELOG.md`](CHANGELOG.md).

### Required Secrets
Configure in GitHub repository settings → Secrets:
- `BOT_TOKEN` - Telegram bot token (bot runtime and notifications)
- `MONGODB_URI` - MongoDB connection string for the bot runtime
- `OWNER_ID` - Your Telegram user ID (initial owner and notifications)
- `BOT_PAT` - Optional Personal Access Token with the `workflow` scope, used by Run Bot to self-chain into the next run for seamless 24/7 coverage
- `GITHUB_TOKEN` - Auto-provided by GitHub Actions

## Where to look next

- For project guide and contributor rules, see [`AGENTS.md`](AGENTS.md).
- For current project state, runtime flow, priorities, and maintenance plan, see [`PLAN.md`](PLAN.md).
- For Replit deployment notes, see [`replit.md`](replit.md).
- For developer documentation overview and detailed guide index, see [`docs/README.md`](docs/README.md).
- For local, Docker, and hosted setup workflow, see [`docs/setup.md`](docs/setup.md).
- For module boundaries and command ownership, see [`docs/modules/modules.md`](docs/modules/modules.md).
- For database layer notes and indexes, see [`docs/databases/databases.md`](docs/databases/databases.md).
- For shared helper documentation, see [`docs/helper/helper.md`](docs/helper/helper.md).
- For utility module notes, see [`docs/utils/utils.md`](docs/utils/utils.md).
- For user-facing flow overview, see [`docs/workflows.md`](docs/workflows.md). For conversation internals, see [`docs/workflows/workflows.md`](docs/workflows/workflows.md).
- For appeals flow, see [`docs/appeal-detailed.md`](docs/appeal-detailed.md). For banning flow, see [`docs/banning-detailed.md`](docs/banning-detailed.md). For roles, see [`docs/role-detailed.md`](docs/role-detailed.md). For warnings, see [`docs/warnings-detailed.md`](docs/warnings-detailed.md).
- For detailed engineering rules, see [`.agents/CLAUDE.md`](.agents/CLAUDE.md), [`.agents/RULES.md`](.agents/RULES.md), [`.agents/STYLE-CODE.md`](.agents/STYLE-CODE.md), [`.agents/STYLE-COMMENTS.md`](.agents/STYLE-COMMENTS.md), and [`.agents/WORKFLOW.md`](.agents/WORKFLOW.md).

## Current Status

- Runtime entry point: `uv run python -m tcbot`.
- Dependency management: `uv` and `uv.lock`.
- Database: MongoDB/Motor with startup index creation.
- Health check: Flask `GET /` endpoint on `PORT`.
- Secrets policy: use environment variables; never commit real tokens, MongoDB URIs, or private chat IDs.

## License

Copyright © 2024-2026 Transsion Core, Dizzy, Ave Studio. All rights reserved.

See `LICENSE` for details.
