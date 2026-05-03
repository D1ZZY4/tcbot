# TCF Telegram Bot

## Overview

A Telegram bot for the Transsion Core Federation (TCF) community. Manages federation-wide bans, appeals, group affiliations, admin promotions, and moderation.

## Architecture

- **Language:** Python 3.11
- **Bot framework:** python-telegram-bot 22.5 (polling mode)
- **Database:** MongoDB (via motor, async)
- **Web server:** Flask (keep-alive / health-check on port 5000)
- **Entry point:** `python3 -m tcbot`
- **Dependency management:** `uv` (lock file: `uv.lock`; `requirements.txt` is legacy and git-ignored)

## Key Modules

| Path | Purpose |
|---|---|
| `tcbot/__init__.py` | Config singleton (`cfg` / `configs`), loaded from env vars |
| `tcbot/__main__.py` | Entry point: logging, Flask keepalive, handler discovery, polling |
| `tcbot/alive.py` | Flask keep-alive server on port 5000 |
| `tcbot/database/mongos.py` | MongoDB client, `connect()`, `col()`, `make_short_id()` |
| `tcbot/database/admins_db.py` | Owners and TC admins collection |
| `tcbot/database/bans_db.py` | Federation bans collection |
| `tcbot/database/queues_db.py` | Promotion-request queue collection |
| `tcbot/database/users_db.py` | Member-cache collection |
| `tcbot/modules/messages.py` | Central `M` namespace for all user-facing strings |
| `tcbot/modules/appeals.py` | Pure functions for appeal business logic |
| `tcbot/modules/admins_ext.py` | Admin service layer (promote, demote, transfer ownership) |
| `tcbot/modules/helper/parse_link.py` | Link builders, HTML helpers (`user_link`, `safe_first_name`), `utcnow()` |
| `tcbot/modules/helper/keyboards.py` | All inline-keyboard factory functions |
| `tcbot/modules/helper/extraction.py` | `extract_target()`, `ResolvedTarget`, `resolve_identity()` |
| `tcbot/utils/prefixes.py` | Prefix filter builder + alt-prefix dispatcher (`_REGISTRY`) |
| `tcbot/utils/logger.py` | `BotLogFormatter` and `setup()` |
| `tcbot/utils/timedate_format.py` | `fmt_dt()` (tz-safe), `utc_now()` |

## Configuration

Secrets are stored in Replit Secrets (environment variables). Non-sensitive config is in `.replit` env vars:

- `BOT_TOKEN` — Telegram bot token (**Replit Secret**)
- `MONGODB_URI` — MongoDB connection string (**Replit Secret**)
- `OWNER_ID` — Initial owner Telegram user ID (env var)
- `DB_NAME` — MongoDB database name (env var, default: "tcbot")
- `MAIN_GROUP` — Main Telegram group/forum chat ID (env var)
- `PORT` — Web server port, set to 5000 for Replit (env var)

The `config.env` file is kept as a local fallback only and is excluded from version control via `.gitignore`.

## Test Suite

Run with: `python3 -m pytest`

61 tests across 8 files — all pass offline (no real bot token or MongoDB needed).
Test dependencies: `pip install pytest pytest-asyncio` (Replit) or `uv sync --extra test` (local).

| File | What it tests |
|---|---|
| `tests/test_format.py` | `tcbot.modules.helper.parse_link` helpers |
| `tests/test_targets.py` | `ResolvedTarget` and `get_reason` |
| `tests/test_users_resolver.py` | `resolve_identity` with mocked repos |
| `tests/test_prefix.py` | Alt-prefix dispatcher and registry |
| `tests/test_keyboards.py` | `tcbot.modules.helper.keyboards` factory shapes |
| `tests/test_messages.py` | `M` string constants |
| `tests/test_appeals_pure.py` | Pure appeal logic functions |
| `tests/test_admins_mod.py` | `admins_ext` service layer with mocked DB |

## Docker

```
docker-compose up --build
```

- `Dockerfile` — uses `uv` (`COPY --from=ghcr.io/astral-sh/uv:latest`) with `uv sync --frozen --no-dev`
- `docker-compose.yml` — `bot` + `mongo:7` services; bot waits for MongoDB health-check

## Deployment

- Workflow: `python3 -m tcbot`
- Port 5000 exposed as the health-check / keep-alive endpoint
- Deployment target: **autoscale**, run command: `python3 -m tcbot`
