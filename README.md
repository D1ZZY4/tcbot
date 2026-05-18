# TCF Bot

This repository keeps its agent, style, and workflow conventions in `agents/`.
Before changing code or documentation, review the guidance there first:
- `agents/RULES.md` - coding conventions, what is forbidden
- `agents/STYLE-CODE.md` - code style, typing, and formatting rules
- `agents/STYLE-COMMENTS.md` - comment and docstring style
- `agents/WORKFLOW.md` - branching, commit conventions, and deployment checklist
- `agents/CLAUDE.md` - project-specific guidance and gotchas
- `agents/REPLIT.md` - Replit environment, config, and secrets guidance

Telegram federation bot for the Transsion Core Federation (TCF) community.

## Features

- **Federation bans** - issue, update, and lift bans that propagate across all affiliated groups
- **Appeals** - deep-link appeal flow with staff review and approve/reject workflow
- **Group management** - connect/disconnect groups, sweep existing bans on join
- **Admin promotions** - request and approve staff role changes with a full audit trail
- **Moderation** - per-group mute, kick, and warn commands
- **Check-me** - users can query their own ban status from the bot
- **Keep-alive** - Flask health-check endpoint on port 5000

## Stack

| Component | Version |
|---|---|
| Python | 3.13 |
| python-telegram-bot | 22.5 |
| Motor (async MongoDB) | latest |
| Flask | latest |

## Quick Start

### Local

```bash
# 1. Copy and fill in your secrets
cp config.env.example config.env

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

## Configuration

All secrets go in `config.env` (gitignored). See `config.env.example` for the full list.

| Variable | Required | Description |
|---|---|---|
| `BOT_TOKEN` | Yes | Telegram bot token from @BotFather |
| `OWNER_ID` | Yes | Telegram user ID of the federation owner |
| `MONGODB_URI` | Yes | MongoDB connection string |
| `DB_NAME` | No | Database name (default: `tcbot`) |
| `COMMUNITY_NAME` | No | Display name used in bot messages |
| `LOGS` | Yes | Log channel chat ID (optionally `chat_id/thread_id`) |
| `PROOFS` | Yes | Proof channel chat ID (optionally `chat_id/thread_id`) |
| `APPEALS` | Yes | Appeal channel chat ID (optionally `chat_id/thread_id`) |
| `MAIN_GROUP` | Yes | Main group/forum chat ID for appeal review posts |
| `PROOF_TIMEOUT_SECONDS` | No | Ban proof step timeout (default: 120) |
| `APPEAL_TIMEOUT_SECONDS` | No | Appeal flow timeout (default: 300) |

## Project Structure

```
tcbot/
├── __init__.py          Config singleton
├── __main__.py          Entry point
├── alive.py             Flask keep-alive
├── database/            MongoDB collection helpers
├── modules/
│   ├── helper/          Shared keyboards, formatters, workflows
│   └── *.py             Command modules (ban, appeal, mute, kick, …)
└── utils/               Logger, prefix builder, datetime helpers
tests/                   Offline unit tests (pytest)
agents/                  Agent/AI coding guidelines
```

## Documentation

- [Documentation hub](docs/index.md)
- [Project architecture](docs/architecture.md)
- [Modules and service boundaries](docs/modules.md)
- [Conversation flows and workflows](docs/workflows.md)
- [Development workflow and onboarding](docs/development.md)
- [AI / agent guidelines](docs/agent-guidelines.md)
- [Agent instructions for Claude](agents/CLAUDE.md)
- [Code style guidelines](agents/STYLE-CODE.md)
- [Comment style guidelines](agents/STYLE-COMMENTS.md)
- [Workflow expectations](agents/WORKFLOW.md)
- [Project rules and constraints](agents/RULES.md)

## Tests

```bash
python3 -m pytest tests/ -q
```

121 tests - all run offline without a bot token or MongoDB connection.

## License

Copyright © 2024–2026 Transsion Core, Dizzy, Aveum Apps. All rights reserved.
See [LICENSE](LICENSE) for details.
