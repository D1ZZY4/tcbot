# TCF Bot

Telegram federation management bot for the Transsion Core Federation (TCF) community. Manages federation-wide bans, user appeals, staff roles, group moderation, and audit logging across all affiliated groups simultaneously.

Before changing any code or documentation, read the agent guidance in `agents/` first — especially `agents/RULES.md` and `agents/STYLE-CODE.md`.

---

## Features

- **Federation bans** — issue, update, and lift bans that propagate across all connected groups instantly
- **Appeals** — deep-link appeal flow with staff review, priority window, approve/reject workflow
- **Group management** — connect and disconnect groups, sweep existing bans on join
- **Staff promotions** — request and approve role changes with a full audit trail
- **Moderation** — per-group mute (with duration), kick, and warn commands
- **Check-me** — users can query their own ban status from the bot PM
- **Keep-alive** — Flask health-check endpoint on port 8080

---

## Stack

| Component | Version |
|---|---|
| Python | 3.12 |
| python-telegram-bot | 22.5 |
| Motor (async MongoDB) | 3.7+ |
| Flask | 3.1+ |
| pytest + pytest-asyncio | test suite only |

---

## Running on Replit

This project is hosted on Replit. Secrets are stored in Replit Secrets — not in `config.env`.

| Secret | Description |
|---|---|
| `BOT_TOKEN` | Telegram bot token from @BotFather |
| `MONGODB_URI` | MongoDB connection string (Atlas or other) |

All other configuration is managed as Replit environment variables. See `config.env.example` for the full list of keys.

**Start the bot:** use the `Start application` workflow (`python3 -m tcbot`).

---

## Running Locally

```bash
# 1. Copy and fill in your config (including secrets for local dev)
cp config.env.example config.env
# Edit config.env — add BOT_TOKEN, MONGODB_URI, and all other required values

# 2. Install dependencies
uv sync

# 3. Run
python3 -m tcbot
```

### Docker

```bash
docker-compose up --build
```

The compose file starts the bot and a local MongoDB instance. The bot waits for MongoDB to pass its health-check before connecting.

---

## Configuration Reference

| Variable | Required | Description |
|---|---|---|
| `BOT_TOKEN` | Yes | Telegram bot token from @BotFather |
| `OWNER_ID` | Yes | Positive Telegram user ID of the federation founder |
| `MONGODB_URI` | Yes | MongoDB connection string |
| `DB_NAME` | No | Database name (default: `tcbot`) |
| `COMMUNITY_NAME` | No | Display name used in bot messages |
| `MAIN_GROUP` | Yes | Main group/forum chat ID for appeal review cards |
| `MAIN_CHANNEL` | No | Main announcement channel chat ID |
| `LOGS` | Yes | Log channel: `chat_id` or `chat_id/thread_id` |
| `LOGS_ERRORS` | No | Error log destination (same format as LOGS) |
| `PROOFS` | Yes | Ban proof channel: `chat_id` or `chat_id/thread_id` |
| `APPEALS` | Yes | Appeal record channel: `chat_id` or `chat_id/thread_id` |
| `APPEAL_LOG_HANDLE` | No | Public `@handle` shown in appeal instructions (default: `@TranssionCoreFederationLogs`) |
| `APPEAL_DISCUSSION_TOPIC` | Yes | Thread ID inside MAIN_GROUP for appeal review cards |
| `PROOF_TIMEOUT_SECONDS` | No | Ban proof conversation timeout (default: 100) |
| `APPEAL_TIMEOUT_SECONDS` | No | Appeal conversation timeout (default: 600) |
| `ALBUM_DEBOUNCE_SECONDS` | No | Album message grouping window (default: 2) |
| `PREFIXES` | No | Command prefixes list (default: `["/", "!", "."]`) |
| `PORT` | No | Flask keepalive port (default: 5000, Replit uses 8080) |
| `LOG_LEVEL` | No | Log verbosity: DEBUG/INFO/WARNING/ERROR (default: INFO) |
| `MODULES_LOAD` | No | Comma-separated allowlist of modules to load |
| `MODULES_NO_LOAD` | No | Comma-separated denylist of modules to skip |

---

## Project Structure

```
tcbot/
├── __init__.py          Config singleton (Configs dataclass + cfg adapter)
├── __main__.py          Entry point, handler registration, polling
├── alive.py             Flask keepalive thread
├── database/            Async MongoDB collection helpers (one file per collection)
├── modules/
│   ├── __init__.py      Module discovery, filtering, and handler collection
│   ├── helper/          Shared keyboards, formatters, decorators, workflows
│   │   └── workflows/   ConversationHandler flows (*_flow.py only, no *_conv.py)
│   └── *.py             Command modules (banning, muting, kicking, appeals, …)
└── utils/               Logger, dispatcher, prefix builder, datetime helpers
agents/                  AI agent instructions (RULES, STYLE-CODE, CLAUDE, etc.)
docs/                    Developer documentation (architecture, modules, workflows)
tests/                   Offline unit tests (121 tests, no token/DB required)
config.env               Local dev config (gitignored; secrets go in Replit Secrets)
config.env.example       Template for new deployments
```

---

## Tests

```bash
python3 -m pytest tests/ -v
```

121 tests — all run fully offline without a bot token or MongoDB connection.

| File | What it covers |
|---|---|
| `test_format.py` | `parse_link` HTML helpers |
| `test_targets.py` | `ResolvedTarget` and `get_reason` |
| `test_users_resolver.py` | `resolve_identity` with mocked repos |
| `test_prefix.py` | Alt-prefix dispatcher and registry |
| `test_keyboards.py` | Keyboard factory shapes |
| `test_decorators.py` | `log_execution` tracer |
| `test_appeals_pure.py` | Pure appeal guard functions |
| `test_log_templates.py` | Log message formatters |
| `test_rate_limiter.py` | `_RateLimiter` sliding-window logic |

## Code Quality

```bash
uv run ruff format .
uv run ruff check --fix .
```

Use `ruff format` for automatic prettifying and `ruff check --fix` to clean up lint
issues such as unused imports and import order.

---

## Documentation

- [Execution plan and project state](PLAN.md)
- [Documentation hub](docs/index.md)
- [Architecture](docs/architecture.md)
- [Modules and service boundaries](docs/modules.md)
- [Conversation flows](docs/workflows.md)
- [Development workflow and onboarding](docs/development.md)
- [AI agent instructions](agents/CLAUDE.md)
- [Code style](agents/STYLE-CODE.md)
- [Comment style](agents/STYLE-COMMENTS.md)
- [Project rules](agents/RULES.md)
- [Workflow conventions](agents/WORKFLOW.md)
- [Replit environment](agents/REPLIT.md)

---

## License

Copyright © 2024–2026 Transsion Core, Dizzy, Aveum Apps. All rights reserved.  
See [LICENSE](LICENSE) for details.
