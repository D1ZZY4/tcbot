# Replit Deployment Notes

This file describes how to run TCF Bot on Replit or a similar hosted environment. It is intentionally focused on deployment and environment setup. For general architecture and development guidance, see [`README.md`](README.md) and [`AGENTS.md`](AGENTS.md). For local and Docker setup, see [`docs/getting-started/setup.md`](docs/getting-started/setup.md). For automation and CI/CD workflows, see [`docs/operations/ci-cd.md`](docs/operations/ci-cd.md).

## Runtime Summary

- Entry point: `uv run python -m tcbot`
- Python project target: 3.12 (`pyproject.toml` requires `>=3.12`)
- Bot framework: `python-telegram-bot` (plain, no `[job-queue]` extra; APScheduler 4.x handles scheduling), tracking the latest compatible release
- Database: MongoDB through Motor
- Cache: in-memory `TwoLevelCache` (L1) + optional Redis L2 (`REDIS_URL`)
- Scheduler: APScheduler 4.x `AsyncScheduler` with `MongoDBDataStore` + `CBORSerializer` (persistent across restarts)
- Transport: webhook mode when explicit `WEBHOOK_URL` or `REPLIT_DEV_DOMAIN` is available (explicit URL takes precedence; local dev falls back to polling)
- Health check + webhook receiver: Flask app on `0.0.0.0:${PORT}` -- `GET /` returns `OK`, `POST /webhook` receives Telegram updates
- Dependency manager: `uv`

## Required Secrets

Store credentials in Replit Secrets or the equivalent platform secret manager. Do not commit real values to the repository.

| Secret | Required | Description |
|---|---|---|
| `BOT_TOKEN` | YES | Telegram bot token from BotFather. Format: `1234567890:AAFxxxxxxxx` |
| `MONGODB_URI` | YES | MongoDB connection string, for example MongoDB Atlas. Format: `mongodb+srv://user:pass@cluster.mongodb.net/` |
| `OWNER_ID` | YES | Positive Telegram user ID for the initial Founder account. |
| `REDIS_URL` | NO | Redis connection URL for the optional L2 cache. Without this the bot uses in-memory cache only. Format: `redis://localhost:6379/0` or a managed Redis URL. |

`OWNER_ID` identifies the initial Founder account and should be set as an
environment variable or secret according to your deployment policy.

## Environment Variables

Use `config.env.example` as the complete template. Important variables:

| Variable | Notes |
|---|---|
| `OWNER_ID` | Required positive Telegram user ID for the initial Founder. |
| `DB_NAME` | Optional database name; defaults to `tcbot`. |
| `COMMUNITY_NAME` | Display name used in bot messages and logs. |
| `PREFIXES` | Python-style prefix list, default `["/", "!", "."]`. |
| `PORT` | Flask keep-alive port. Defaults to `5000` if unset, invalid, or outside `1..65535`; set this to the port Replit expects for your deployment. |
| `MAIN_GROUP` | Main community group or forum chat ID. |
| `MAIN_CHANNEL` | Optional announcement channel chat ID. |
| `EXTEND_GROUP` | Optional secondary/staff group chat ID. |
| `PROOFS` | Proof destination: `chat_id` or `chat_id/thread_id`. |
| `LOGS` | Moderation/action log destination: `chat_id` or `chat_id/thread_id`. |
| `LOGS_ERRORS` | Error report destination: same format as `LOGS`. |
| `APPEALS` | Appeal record destination: `chat_id` or `chat_id/thread_id`. |
| `APPEAL_LOG_HANDLE` | Public log handle shown to users in appeal instructions. |
| `APPEAL_DISCUSSION_TOPIC` | Thread ID inside `MAIN_GROUP` where appeal review cards are posted. |
| `PROOF_TIMEOUT_SECONDS` | Ban proof timeout; default `100`; values below `1` fall back to default. |
| `APPEAL_TIMEOUT_SECONDS` | Appeal conversation timeout; default `600`; values below `1` fall back to default. |
| `ALBUM_DEBOUNCE_SECONDS` | Album grouping window; default `2`; values below `1` fall back to default. |
| `LOG_LEVEL` | Logging verbosity; default `INFO`. |
| `MODULES_LOAD` | Optional comma-separated allowlist of module names. |
| `MODULES_NO_LOAD` | Optional comma-separated denylist of module names. |
| `REDIS_URL` | Optional Redis connection URL (e.g. `redis://localhost:6379/0`). When unset the bot uses in-memory L1 cache only; no Redis dependency is required. |
| `WARN_LIMIT` | Per-group warning threshold that triggers an automatic ban; default `3`, minimum `1`. When a user's warn count in one group reaches exactly this value, they are federation-banned and their warns cleared. |
| `WARN_EXPIRY_DAYS` | Days after which warn_count records expire; default `0` (disabled). Set to a positive integer to enable daily APScheduler expiry job. |
| `FED_WARN_LIMIT` | Federation-wide warn threshold that triggers an automatic federation ban; default `0` (disabled). Set to a positive integer (e.g. `5`) to auto-ban a user when their total warn count across **all** connected groups reaches this value. Operates independently of and in addition to the per-group `WARN_LIMIT` auto-ban. |

Destination variables that represent forum topics use this format:

```text
chat_id/thread_id
```

Example shape only:

```text
-1001234567890/42
```

Do not put real private chat IDs in public documentation.

## Install and Run

Install dependencies from the lockfile:

```bash
uv sync
```

Run the bot:

```bash
uv run python -m tcbot
```

If your Replit workflow supports custom commands, set the run command to:

```bash
uv run python -m tcbot
```

The bot fails fast when `BOT_TOKEN`, `MONGODB_URI`, or `OWNER_ID` are missing. It starts webhook transport after MongoDB connection, index creation, owner seeding, handler registration, and error reporter setup complete when `WEBHOOK_URL` or `REPLIT_DEV_DOMAIN` is available. Without a public URL, local development falls back to polling.

```mermaid
flowchart TD
    Secrets[Configure Replit Secrets] --> Env[Set required environment variables]
    Env --> Sync[Run uv sync]
    Sync --> Start[Run uv run python -m tcbot]
    Start --> Ready[Validate startup prerequisites]
    Ready --> Mongo[MongoDB connected]
    Ready --> Indexes[Indexes created]
    Ready --> Owner[Initial owner ensured]
    Ready --> Handlers[Handlers registered]
    Ready --> Reporter[Error reporter attached]
    Ready --> Transport{Public webhook URL?}
    Transport -->|yes| Webhook[Start webhook transport]
    Transport -->|no| Polling[Start local polling fallback]
    Ready --> Health[Expose Flask health check]
    Health --> Ok[GET slash returns OK]
```

## Health Check

`tcbot/alive.py` starts Flask in a daemon thread when `tcbot/__main__.py` calls `start_keepalive()`.

- Host: `0.0.0.0`
- Port: `PORT` from the environment, default `5000`
- `GET /`: returns plain-text `OK` for basic uptime probes.
- `GET /health`: returns a JSON subsystem-status report (`mongodb`, `redis`, `scheduler`, `circuit_telegram`, `circuit_mongodb`, `ts`) with HTTP 200 when all subsystems are ready or HTTP 503 when degraded.

If the hosting platform requires a specific public port, set `PORT` accordingly in the environment. Invalid or out-of-range values fall back to `5000` instead of crashing the health server.

## Code Quality Commands

```bash
uv run ruff format .
uv run ruff check --fix .
```

Use these before committing source changes.

## Deployment Checklist

Before starting the deployment:

- [ ] `BOT_TOKEN` is set in Replit Secrets or the platform secret manager.
- [ ] `MONGODB_URI` is set and reachable from Replit.
- [ ] `OWNER_ID` is set to the correct Telegram user ID.
- [ ] `PORT` matches the hosting platform expectation.
- [ ] Required Telegram destinations (`MAIN_GROUP`, `LOGS`, `PROOFS`, `APPEALS`, and appeal topic settings) are configured.
- [ ] The bot has the necessary permissions in connected groups/channels/forums.
- [ ] `uv run python -m tcbot` succeeds.
- [ ] (Optional) `REDIS_URL` is set if L2 Redis cache is desired.
- [ ] (Optional) `WARN_EXPIRY_DAYS` is set to a positive integer to enable automatic warn expiry.

## Safety Rules

- Do not commit `config.env` with real values.
- Do not paste real tokens, MongoDB URIs, or private chat IDs into Markdown files.
- Do not add dependencies to `requirements.txt`; this project uses `uv`, `pyproject.toml`, and `uv.lock`.
- Keep deployment configuration in environment variables or the platform secret manager.
