# TCF Bot

Telegram federation bot for the Transsion Core Federation (TCF) community.

## Features

- **Federation bans** — issue, update, and lift bans that propagate across all affiliated groups
- **Appeals** — deep-link appeal flow with staff review and approve/reject workflow
- **Group management** — connect/disconnect groups, sweep existing bans on join
- **Admin promotions** — request and approve staff role changes with a full audit trail
- **Moderation** — per-group mute, kick, and warn commands
- **Check-me** — users can query their own ban status from the bot
- **Keep-alive** — Flask health-check endpoint on port 5000

## Stack

| Component | Version |
|---|---|
| Python | 3.11 |
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

## Tests

```bash
python3 -m pytest tests/ -q
```

61 tests — all run offline without a bot token or MongoDB connection.

## License

Copyright © 2024–2026 Transsion Core, Dizzy, Aveum Apps. All rights reserved.
See [LICENSE](LICENSE) for details.
