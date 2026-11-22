# Setup

This page covers local, Docker, and hosted setup for TCF Bot. The project
targets Python 3.14 and uses `uv` for dependency management. For the repository
overview, see the [root README](../README.md); for hosted deployment notes, see
[replit.md](../../replit.md).

## Prerequisites

- Python 3.14, pinned in `.python-version`.
- `uv` for dependency installation and command running.
- PostgreSQL. The bot applies its own Alembic migrations at startup.
- Optional Redis for the L2 cache. Without it the bot runs on in-memory L1
  only.
- A Telegram bot token from BotFather, and Telegram API ID and hash from
  `https://my.telegram.org`.

## Install dependencies

```bash
uv sync --frozen
```

Always use `uv`. Do not use `pip`, `uv pip`, or manual paths into `.venv`.

## Configuration

Copy the template and fill in the values:

```bash
cp config.env.example config.env
```

`python-dotenv` loads `config.env`, falling back to `.env`, when present. In
hosted deployment, use the platform secret manager instead of a file. Never
commit real credentials.

### Required values

| Variable | Purpose |
|---|---|
| `BOT_TOKEN` | Telegram bot token. |
| `DATABASE_URL` | PostgreSQL connection string. |
| `OWNER_ID` | Positive numeric Telegram user id of the initial Owner. |
| `PROOFS` | Negative group or channel id for ban evidence; `chat_id/thread_id` is accepted. Boot refuses without it. |
| `API_ID` | Telegram API id for MTProto lookups. Boot refuses without it. |
| `API_HASH` | Telegram API hash matching `API_ID`. |

### Commonly configured values

| Variable | Default | Purpose |
|---|---|---|
| `COMMUNITY_NAME` | `Bot` | Display name in messages and logs. |
| `PREFIXES` | `["/", "!", "."]` | Command prefixes. |
| `DB_SCHEMA` | `public` | Schema the bot reads and writes: `public`, `test`, or `development`. |
| `DB_POOL_SIZE` | `5` | PostgreSQL pool size. Must fit the server's connection limit. |
| `DB_MAX_OVERFLOW` | `5` | Extra connections under load. |
| `REDIS_URL` | empty | Optional Redis L2 cache. |
| `PG_CRON_ENABLED` | `false` | Let pg_cron own database-only jobs. |
| `MAIN_GROUP` | unset | Primary community group id; must be negative. |
| `MAIN_CHANNEL` | unset | Rules publication target; must be negative. |
| `LOGS`, `LOGS_ERRORS`, `APPEALS` | unset | Log and appeal destinations; `chat_id/thread_id` is accepted. |
| `ALBUM_DEBOUNCE_SECONDS` | `4` | Proof silence window, minimum 1. |
| `WARN_LIMIT` | `3` | Per-group warn threshold, minimum 1. |
| `WARN_EXPIRY_DAYS` | `0` | Warning expiry in days; 0 disables. |
| `FED_WARN_LIMIT` | `0` | Federation-wide warn threshold; 0 disables. |
| `PROMOTION_REQUEST_TTL_DAYS` | `7` | Pending request lifetime; 0 disables expiry. |
| `PORT` | `5000` | Keep-alive and webhook port. |
| `BIND_HOST` | `0.0.0.0` | Listener interface. |
| `WEBHOOK_URL` | empty | Public webhook base URL. Empty falls back to polling. |
| `WEBHOOK_SECRET` | random | Secret token; 1 to 256 characters from the allowed set. |
| `SENTRY_DSN` | empty | Opt-in error monitoring with the observability extra. |
| `MODULES_LOAD`, `MODULES_NO_LOAD` | empty | Module allowlist and denylist. |

Community menu links are derived from `MAIN_CHANNEL`, `MAIN_GROUP`, `LOGS`,
and `APPEALS` through `messages/links.py`; no static URL variables remain.

See [the configuration module](../architecture/repository-map.md) and
`config.env.example` for the full list and validation rules.

## Run locally

```bash
uv run python -m tcbot
```

Without a public webhook URL the bot falls back to long polling. Startup loads
the configuration, starts the Flask health server, connects PostgreSQL,
applies migrations, seeds the initial Owner, registers infrastructure
destinations, connects Redis and MTProto, starts the scheduler, and discovers
handlers.

Health endpoints:

- `GET /` returns `OK`.
- `GET /health` returns a JSON status with HTTP 200 when core subsystems are
  ready and 503 when degraded. Redis is a hint only; a Redis outage does not
  page the instance.
- `GET /metrics` is available when the optional `prometheus-client` extra is
  installed.
- `POST /webhook` receives Telegram updates when webhook mode is active. The
  route checks the secret token in constant time before touching the payload.

## Run with Docker Compose

```bash
docker compose up --build
```

The compose file starts the bot, PostgreSQL, and Redis together. Keep secrets
in the environment or the platform secret manager, not in committed files.

## Hosted webhook deployment

Set `WEBHOOK_URL` to the public HTTPS base URL. The bot registers
`<WEBHOOK_URL>/webhook` with Telegram, verifies the registered URL, and wires
the Flask receiver before accepting updates. `WEBHOOK_SECRET` defaults to a
random token regenerated each restart, which is safe because `set_webhook` is
called with the current value. During shutdown the route returns 503 so
Telegram retries in-flight updates.

On Replit, the dev domain is used only when the process is the Replit
application itself. A workspace shell that starts the bot by hand polls
instead, so updates are not handed to the workflow. Set `WEBHOOK_URL`
explicitly to override this.

## Validate the setup

```bash
uv run ruff format .
uv run ruff check .
uv run pyright .
uv run pytest tests/ -q
```

Database-backed tests use the `test` schema and skip when no server is
configured. See [CI/CD](../operations/ci-cd.md) for the workflows and
[backup and restore](../operations/backup-and-restore.md) for database
operations.

## First-run checklist

1. Confirm `PROOFS` is a negative group or channel id the bot can post to.
2. Confirm `API_ID` and `API_HASH` are set so boot does not refuse to start.
3. Confirm the configured `OWNER_ID` can be reached by the bot.
4. Send `/start` in private chat and check the main menu.
5. Connect the primary group through `/tcconnect`.
6. Post a test log action and confirm delivery to `LOGS`.
