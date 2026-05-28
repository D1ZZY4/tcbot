# TCF Bot

TCF Bot is a Telegram federation management bot for the Transsion Core Federation community. It coordinates moderation across connected groups, records audit trails, supports appeal review, and exposes a small Flask health-check endpoint for hosted environments.

## Features

- **Federation bans** — create, update, and lift bans across all connected groups.
- **Ban proof workflow** — collect proof media/text before enforcement and store proof message references.
- **Appeals** — deep-link private-message flow with staff review buttons and appeal records.
- **Connected groups** — approve group joins, track active groups, and run multi-group actions safely.
- **Staff roles** — Founder, Admin, Developer, and Tester hierarchy with promotion/demotion workflows.
- **Moderation actions** — ban, unban, kick, mute, warn, warning reset, checks, stats, and broadcast helpers.
- **Audit logging** — moderation, appeal, role, and error reports to configured log destinations.
- **Health checks** — Flask keep-alive server on `PORT` with `GET /` returning `OK`.

## Stack

| Component | Current project setting |
|---|---|
| Python | 3.12 project target (`requires-python = ">=3.12"`) |
| Bot framework | `python-telegram-bot[job-queue] == 22.5` |
| Database | MongoDB through Motor (`motor >= 3.7.1`) |
| Health server | Flask (`flask >= 3.1.0`) |
| Configuration | Environment variables, with `python-dotenv` loading local `config.env` |
| Dependency manager | `uv` with `uv.lock` |
| Formatting/linting | Ruff |
| Tests | pytest + pytest-asyncio offline suite |

## Quick Start

### 1. Install dependencies

```bash
uv sync
```

For tests, include the optional test dependencies:

```bash
uv sync --extra test
```

### 2. Configure environment

For local development, copy the template and fill in your own values:

```bash
cp config.env.example config.env
```

Never commit real credentials. At minimum, the bot needs:

- `BOT_TOKEN` — Telegram bot token from BotFather.
- `MONGODB_URI` — MongoDB connection string.
- `OWNER_ID` — Telegram user ID for the initial federation founder.

See [Configuration](#configuration) below and `config.env.example` for the complete list.

### 3. Run the bot

```bash
python3 -m tcbot
```

On Windows, use this if `python3` is not available:

```bash
python -m tcbot
```

## Docker Compose

```bash
docker-compose up --build
```

The compose setup starts the bot and a local `mongo:7` service. The bot reads `config.env` and waits for MongoDB to pass its health check.

## Replit / Hosted Deployment

Use Replit Secrets or the hosting platform's secret manager for credentials. Do not store tokens or MongoDB URIs in committed files.

Recommended run command:

```bash
python3 -m tcbot
```

The Flask keep-alive server binds to `0.0.0.0:${PORT}`. If `PORT` is unset, invalid, or outside `1..65535`, the application defaults to `5000`.

See `replit.md` for Replit-specific setup notes.

## Configuration

Configuration is loaded from environment variables in `tcbot/__init__.py`. For local development, `python-dotenv` reads `config.env` if it exists. Startup fails fast when required runtime values such as `BOT_TOKEN`, `MONGODB_URI`, or `OWNER_ID` are missing.

| Variable | Required | Description |
|---|---:|---|
| `BOT_TOKEN` | Yes | Telegram bot token from BotFather. |
| `OWNER_ID` | Yes | Positive Telegram user ID seeded as the initial Founder. |
| `MONGODB_URI` | Yes | MongoDB connection string. |
| `DB_NAME` | No | MongoDB database name, default `tcbot`. |
| `COMMUNITY_NAME` | No | Display name used in bot messages and logs. |
| `PREFIXES` | No | Python-style list of command prefixes, default `["/", "!", "."]`. |
| `PORT` | No | Flask keep-alive port, default `5000`; invalid or out-of-range values fall back to `5000`. |
| `MAIN_GROUP` | Usually | Main community group/forum chat ID. |
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

```text
Telegram updates
  ↓
python-telegram-bot Application (`tcbot/__main__.py`)
  ↓
Global rate limiter (group -1)
  ↓
Dynamically discovered command modules (`tcbot/modules/*.py`)
  ↓
Shared helpers and workflows (`tcbot/modules/helper/`)
  ↓
Database helpers (`tcbot/database/*_db.py`)
  ↓
MongoDB via Motor
```

Key runtime pieces:

- `tcbot/__init__.py` loads environment configuration into an immutable dataclass and exposes the `cfg` adapter.
- `tcbot/__main__.py` starts logging, launches Flask keep-alive, builds the PTB application, registers handlers, connects MongoDB in `post_init`, and starts long polling.
- `tcbot/modules/__init__.py` discovers top-level modules, collects their `__handlers__` lists, and fails startup if an enabled module cannot be imported.
- `tcbot/database/mongos.py` owns the Motor client, database accessor, short ID generator, and index setup.
- `tcbot/utils/dispatch.py` provides bounded concurrent fan-out for multi-group Telegram API calls.
- `tcbot/utils/error_reporter.py` receives handler, asyncio, and logging errors for reporting to the configured error destination.

## Repository Layout

```text
tgbot/
├── tcbot/                    Bot package
│   ├── database/             Async MongoDB helper modules
│   ├── modules/              Command modules and Telegram handlers
│   │   └── helper/           Formatters, decorators, keyboards, workflows
│   │       └── workflows/    Conversation flows (`*_flow.py`)
│   └── utils/                Logging, prefixes, dispatch, datetime helpers
├── tests/                    Offline pytest tests
├── docs/                     Developer subsystem documentation
├── agents/                   Detailed agent and contributor rules
├── config.env.example        Environment template
├── docker-compose.yml        Bot + MongoDB local compose setup
├── pyproject.toml            Project metadata, dependencies, pytest, Ruff
├── uv.lock                   Locked dependency graph
├── AGENTS.md                 Project guide for agents/contributors
├── PLAN.md                   Current project state and improvement plan
└── replit.md                 Replit deployment notes
```

## Tests

The current collected inventory is 125 tests across 14 `tests/test_*.py` files. The suite is designed to run offline without a real Telegram token or MongoDB connection.

Run the full suite:

```bash
uv run --extra test pytest tests/ -v
```

Collect tests only:

```bash
uv run --extra test pytest --collect-only -q
```

The pytest configuration lives in `pyproject.toml`.

## Code Quality

```bash
uv run ruff format .
uv run ruff check --fix .
```

Ruff targets Python 3.12 and line length 88. GitHub Actions install dependencies through `uv sync --frozen` / `uv sync --extra test --frozen` so CI follows `pyproject.toml` and `uv.lock`. Project code should follow the detailed rules in `agents/CLAUDE.md`, `agents/RULES.md`, `agents/STYLE-CODE.md`, and `agents/STYLE-COMMENTS.md`.

## Documentation Index

- `AGENTS.md` — project guide for agents and contributors.
- `PLAN.md` — current state, runtime flow, priorities, and maintenance plan.
- `replit.md` — Replit deployment notes.
- `docs/README.md` — developer documentation overview and detailed guide index.
- `docs/setup.md` — local, Docker, and hosted setup workflow.
- `docs/modules/modules.md` — module boundaries.
- `docs/databases/databases.md` — database layer notes.
- `docs/helper/helper.md` — shared helper documentation.
- `docs/utils/utils.md` — utility module notes.
- `docs/workflows.md` and `docs/workflows/workflows.md` — user-facing flow overview and conversation internals.
- `docs/appeal-detailed.md`, `docs/banning-detailed.md`, `docs/role-detailed.md`, `docs/warnings-detailed.md` — detailed feature guides.
- `agents/CLAUDE.md`, `agents/RULES.md`, `agents/STYLE-CODE.md`, `agents/STYLE-COMMENTS.md`, `agents/WORKFLOW.md` — detailed engineering rules.

## Current Status

- Runtime entry point: `python3 -m tcbot`.
- Dependency management: `uv` and `uv.lock`.
- Database: MongoDB/Motor with startup index creation.
- Health check: Flask `GET /` endpoint on `PORT`.
- Test inventory: 125 collected tests across 14 files.
- Secrets policy: use environment variables; never commit real tokens, MongoDB URIs, or private chat IDs.

## License

Copyright © 2024–2026 Transsion Core, Dizzy, Aveum Apps. All rights reserved.

See `LICENSE` for details.
