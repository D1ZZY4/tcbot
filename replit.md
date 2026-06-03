# Replit Deployment Notes

This file describes how to run TCF Bot on Replit or a similar hosted environment. It is intentionally focused on deployment and environment setup. For general architecture and development guidance, see [`README.md`](README.md), [`AGENTS.md`](AGENTS.md), and [`PLAN.md`](PLAN.md). For local and Docker setup, see [`docs/setup.md`](docs/setup.md). For automation and CI/CD workflows, see [`docs/workflows-guide.md`](docs/workflows-guide.md).

## Runtime Summary

- Entry point: `uv run python -m tcbot`
- Python project target: 3.12 (`pyproject.toml` requires `>=3.12`)
- Bot framework: `python-telegram-bot[job-queue] == 22.5`
- Database: MongoDB through Motor
- Health check: Flask app on `0.0.0.0:${PORT}` with `GET /` returning `OK`
- Dependency manager: `uv`

## Required Secrets

Store credentials in Replit Secrets or the equivalent platform secret manager. Do not commit real values to the repository.

| Secret | Description |
|---|---|
| `BOT_TOKEN` | Telegram bot token from BotFather. |
| `MONGODB_URI` | MongoDB connection string, for example MongoDB Atlas. |

`OWNER_ID` is also required for startup. It is not a credential, but it identifies the initial Founder account and should be set as an environment variable or secret according to your deployment policy.

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

The bot fails fast when `BOT_TOKEN`, `MONGODB_URI`, or `OWNER_ID` are missing. It starts polling Telegram after MongoDB connection, index creation, owner seeding, handler registration, and error reporter setup complete.

## Health Check

`tcbot/alive.py` starts Flask in a daemon thread when `tcbot/__main__.py` calls `start_keepalive()`.

- Host: `0.0.0.0`
- Port: `PORT` from the environment, default `5000`
- Endpoint: `GET /`
- Response: `OK`

If the hosting platform requires a specific public port, set `PORT` accordingly in the environment. Invalid or out-of-range values fall back to `5000` instead of crashing the health server.

## Tests on Replit

Install test extras and run the offline suite:

```bash
uv sync --extra test
uv run --extra test pytest tests/ -v
```

Collect tests without executing them:

```bash
uv run --extra test pytest --collect-only -q
```

Current collected inventory: 1251 tests across 71 test files. Tests are designed to run without a real bot token or MongoDB connection.

## Code Quality Commands

```bash
uv run ruff format .
uv run ruff check --fix .
```

Use these before committing source changes. For documentation-only changes, a pytest collection check is normally sufficient.

## Deployment Checklist

Before starting the deployment:

- [ ] `BOT_TOKEN` is set in Replit Secrets or the platform secret manager.
- [ ] `MONGODB_URI` is set and reachable from Replit.
- [ ] `OWNER_ID` is set to the correct Telegram user ID.
- [ ] `PORT` matches the hosting platform expectation.
- [ ] Required Telegram destinations (`MAIN_GROUP`, `LOGS`, `PROOFS`, `APPEALS`, and appeal topic settings) are configured.
- [ ] The bot has the necessary permissions in connected groups/channels/forums.
- [ ] `uv run python -m tcbot` succeeds.
- [ ] `uv run --extra test pytest --collect-only -q` succeeds.

## Safety Rules

- Do not commit `config.env` with real values.
- Do not paste real tokens, MongoDB URIs, or private chat IDs into Markdown files.
- Do not add dependencies to `requirements.txt`; this project uses `uv`, `pyproject.toml`, and `uv.lock`.
- Keep deployment configuration in environment variables or the platform secret manager.
