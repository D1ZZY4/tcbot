# Setup

This page covers local, Docker, and hosted setup. The project targets Python
3.14 and uses `uv` for dependency management. For the repository overview use
the [root README](../../README.md); for Replit notes use
[replit.md](../../replit.md).

## Prerequisites

- Python 3.14, pinned in `.python-version`.
- `uv` for dependency installation and command running.
- PostgreSQL. The bot applies its own Alembic migrations at startup.
- Optional Redis for the L2 cache. Without it the bot runs on in-memory L1 only.
- A Telegram bot token from BotFather and API credentials from `https://my.telegram.org`.

## Install

```bash
uv sync --frozen
```

Always use `uv`, never `pip`, `uv pip`, or manual paths into `.venv`.

## Configuration

Copy the template and fill it in:

```bash
cp config.env.example config.env
```

`python-dotenv` loads `config.env`, falling back to `.env`, when present. In
hosted deployments use the platform secret manager instead of a file. Never
commit real credentials. The complete list of variables, defaults, and
validation rules is in [Configuration](../reference/configuration.md).

Required values:

| Variable | Purpose |
|---|---|
| `BOT_TOKEN` | Telegram bot token. |
| `DATABASE_URL` | PostgreSQL connection string. |
| `OWNER_ID` | Positive numeric Telegram user id of the initial Owner. |
| `PROOFS` | Negative group or channel id for ban evidence; `chat_id/thread_id` is accepted. Boot refuses without it. |
| `API_ID` | Telegram API id for MTProto lookups. Boot refuses without it. |
| `API_HASH` | Telegram API hash matching `API_ID`. |

Commonly configured values:

| Variable | Default | Purpose |
|---|---|---|
| `COMMUNITY_NAME` | `Bot` | Display name in messages and logs. |
| `PREFIXES` | `["/", "!", "."]` | Command prefixes. |
| `DB_SCHEMA` | `public` | Schema the bot reads and writes: `public`, `test`, or `development`. |
| `DB_POOL_SIZE`, `DB_MAX_OVERFLOW` | `5`, `5` | Connection pool size and overflow. Must fit the server limit. |
| `REDIS_URL` | empty | Optional Redis L2 cache. |
| `PG_CRON_ENABLED` | `false` | Let pg_cron own database-only jobs. |
| `MAIN_GROUP` | unset | Primary community group id; must be negative. |
| `MAIN_CHANNEL` | unset | Rules publication target; must be negative. |
| `LOGS`, `LOGS_ERRORS`, `APPEALS` | unset | Log and appeal destinations; `chat_id/thread_id` is accepted. |
| `ALBUM_DEBOUNCE_SECONDS` | `4` | Proof silence window, minimum 1. |
| `WARN_LIMIT`, `WARN_EXPIRY_DAYS`, `FED_WARN_LIMIT` | `3`, `0`, `0` | Warning thresholds and expiry. |
| `PROMOTION_REQUEST_TTL_DAYS` | `7` | Pending request lifetime; 0 disables expiry. |
| `PORT`, `BIND_HOST` | `5000`, `0.0.0.0` | Keep-alive and webhook listener. |
| `WEBHOOK_URL`, `WEBHOOK_SECRET` | empty, random | Webhook transport. |
| `SENTRY_DSN` | empty | Opt-in error monitoring with the observability extra. |
| `MODULES_LOAD`, `MODULES_NO_LOAD` | empty | Module allowlist and denylist. |
| `MTPROTO_SESSION` | `tcbot_mtproto` | Namespace for the shared MTProto session in PostgreSQL. |

Community menu links derive from `MAIN_CHANNEL`, `MAIN_GROUP`, `LOGS`, and
`APPEALS` through `messages/links.py`; no static URL variables remain.

## Run locally

```bash
uv run python -m tcbot
```

Without a public webhook URL the bot falls back to long polling. Startup loads
the configuration, starts the Flask health server, connects PostgreSQL, applies
migrations, seeds the Owner, registers destinations, connects Redis and MTProto,
starts the scheduler, and discovers handlers. Health endpoints:

- `GET /` returns `OK`.
- `GET /health` returns JSON with HTTP 200 when core subsystems are ready and
  503 when degraded. Redis is a hint only; a Redis outage does not page the instance.
- `GET /metrics` is available when the optional `prometheus-client` extra is installed.
- `POST /webhook` receives Telegram updates in webhook mode. The route checks the
  secret token in constant time before touching the payload.

## Run with Docker Compose

```bash
cp config.env.example .env
# Fill in .env before starting: compose reads it through env_file.
docker compose up --build
```

The compose file starts the bot, PostgreSQL, and Redis, and reads runtime
settings from `.env`. Keep secrets in the environment or the platform secret
manager, not in committed files.

## Hosted webhook deployment

Set `WEBHOOK_URL` to the public HTTPS base URL. The bot registers
`<WEBHOOK_URL>/webhook`, verifies the registered URL, and wires the Flask
receiver before accepting updates. `WEBHOOK_SECRET` defaults to a random token
regenerated each restart, which is safe because `set_webhook` uses the current
value. During shutdown the route returns 503 so Telegram retries in-flight
updates.

On Replit the dev domain is used only when the process is the Replit
application itself. A workspace shell that starts the bot by hand polls
instead. Set `WEBHOOK_URL` explicitly to override this.

## Validate

```bash
uv run ruff format --check .
uv run ruff check .
uv run pyright .
uv run pytest tests/ -q
```

Database-backed tests use the `test` schema and skip when no server is
configured. See [CI/CD](../operations/ci-cd.md) for the workflows and
[Backup and restore](../operations/backup-and-restore.md) for database operations.

## First-run checklist

1. Confirm `PROOFS` is a negative group or channel id the bot can post to.
2. Confirm `API_ID` and `API_HASH` are set so boot does not refuse to start.
3. Confirm the configured `OWNER_ID` can be reached by the bot.
4. Send `/start` in private chat and check the main menu.
5. Connect the primary group through `/tcconnect`.
6. Post a test log action and confirm delivery to `LOGS`.
