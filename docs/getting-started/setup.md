# Setup Guide

This guide explains how to run TCF Bot locally, with Docker, or in a hosted environment without committing secrets.

For the project overview, see [`../../README.md`](../../README.md). For
Replit-specific deployment, see [`../../replit.md`](../../replit.md).

## Prerequisites

- Python 3.14 (the pinned runtime for local, Docker, and Vercel; the
  package floor is `>=3.14` and it is also the tested runtime).
- [`uv`](https://docs.astral.sh/uv/) for dependency and lockfile management.
- A Telegram bot token from BotFather.
- A PostgreSQL deployment, local or hosted (the bot applies its own schema migrations).
- Telegram destination chats for logs, errors, proofs, and appeals.

## Local setup

```bash
git clone <repo-url>
cd tcbot
uv sync --frozen
cp config.env.example config.env
uv run python -m tcbot
```

The local command loads `config.env` through `python-dotenv`. Fill in the
required values before starting the bot.

Use `uv run python -m tcbot` so the locked `uv` environment is used regardless of whether your platform exposes Python as `python` or `python3`.

Format and lint after edits:

```bash
uv run ruff format .
uv run ruff check --fix .
uv run pyright .
```

## Docker setup

The repository includes a Docker Compose stack with the bot, `postgres:16-alpine`,
and Redis. Compose reads `.env`, not `config.env`, and maps the bot's port as
`${PORT:-5000}:${PORT:-5000}`. Create a Docker-specific environment file before
starting the stack:

```bash
cp config.env.example .env
# Edit .env and set at least:
# DATABASE_URL=postgresql://tcbot:tcbot@postgres:5432/tcbot
# REDIS_URL=redis://redis:6379/0
docker compose up --build
```

Set `BOT_TOKEN`, `OWNER_ID`, and the destination variables required by the
features you enable in `.env`. The `bot` service waits for both PostgreSQL and
Redis health checks before startup. The image runs:

```bash
uv run --frozen python -m tcbot
```

## Hosted setup

For Replit or another hosting platform:

1. Store `BOT_TOKEN`, `DATABASE_URL`, and `OWNER_ID` in the platform secret
   manager or its environment configuration.
2. Store the required destination values (`LOGS`, plus `PROOFS` and `APPEALS`
   when those features are enabled) as environment variables or secrets.
3. Start the bot with `uv run python -m tcbot`.
4. Make sure the Flask health endpoint port matches `PORT`.

Do not commit a filled `config.env` file.

Per-platform tutorials (GitHub Actions 24/7 runner, Vercel serverless,
Docker, Heroku, VPS with systemd, Windows over RDP) live in the collapsible
`Deployment` section of [`../../README.md`](../../README.md#deployment).

### Community links (optional)

The Additional Links menu in the bot start screen shows all five buttons by default: Main Channel, Discussion Group, Logs Channel, Appeals Channel, and TRAVEL. Each reads `COMMUNITY_*_URL`; a non-empty env value overrides the built-in default, and empty falls back to it, so a fresh deployment shows every button with zero setup. A non-http(s) env value is rejected: it logs a warning and that button is omitted.

| Variable | Button label |
|---|---|
| `COMMUNITY_CHANNEL_URL` | Main Channel |
| `COMMUNITY_GROUP_URL` | Discussion Group |
| `COMMUNITY_LOGS_URL` | Logs Channel |
| `COMMUNITY_APPEAL_URL` | Appeals Channel |
| `COMMUNITY_TRAVEL_URL` | TRAVEL - Transsion Development (Community) |

## Environment variable format

The configuration loader reads environment variables in `tcbot/__init__.py`. Local development uses `python-dotenv` to load `config.env`.

Recommended `config.env` syntax:

```env
BOT_TOKEN="<telegram-bot-token>"
OWNER_ID="123456789"
DATABASE_URL="postgresql://<user>:<password>@<host>:5432/tcbot"
COMMUNITY_NAME="TCF - Transsion Core Federation"
PREFIXES='["/", "!", "."]'
PORT="5000"
```

Values that are parsed as `chat_id/thread_id` must use an integer chat ID and optional integer thread ID separated by `/`:

```env
PROOFS="-1001234567890/67"
LOGS="-1001234567890/42"
LOGS_ERRORS="-1001234567890/279"
APPEALS="-1001234567890/12"
```

Use a plain chat ID when no topic thread is needed:

```env
PROOFS="-1001234567890"
```

## Configuration reference

| Variable | Required | Format | Purpose |
|---|---:|---|---|
| `BOT_TOKEN` | Yes | string | Telegram bot token. Never commit it. |
| `OWNER_ID` | Yes | positive integer | Initial Founder user ID. Startup fails if missing or invalid. |
| `DATABASE_URL` | Yes | PostgreSQL URL | SQLAlchemy connection string, e.g. `postgresql://user:password@host:5432/tcbot`. The bot applies the schema migrations at startup, so the role needs permission to create tables. Never commit it. |
| `COMMUNITY_NAME` | No | string | Display name in messages and logs. Defaults to `Bot`. |
| `PREFIXES` | No | Python-style list or CSV | Command prefixes. Default is `["/", "!", "."]`. |
| `PORT` | No | integer or `auto` | Flask keep-alive port. `auto`, invalid, or out-of-range values resolve to `5000`. |
| `MAIN_GROUP` | Usually | integer chat ID | Main community group or forum. |
| `PROOFS` | Usually | `chat_id` or `chat_id/thread_id` | Destination for ban proof media. Defaults to the community proof channel (`-1003997518221`); override to use a different chat or forum thread. |
| `LOGS` | Yes | `chat_id` or `chat_id/thread_id` | Audit-log destination. |
| `LOGS_ERRORS` | Recommended | `chat_id` or `chat_id/thread_id` | Error-report destination. When empty, reports fall back to the owner DM instead of being dropped. |
| `APPEALS` | Yes for appeals | `chat_id` or `chat_id/thread_id` | Submitted appeal record destination (channel, group, or forum thread). Also receives a copy of every review card, so one value covers all appeal surfaces. The appeal instruction handle is derived from the public logs link (`COMMUNITY_LOGS_URL`), so no separate handle variable is needed. |
| `ALBUM_DEBOUNCE_SECONDS` | No | integer seconds | Proof silence window for ban proof media. Default `4`; values below `1` fall back to default. |
| `API_ID` | Yes | integer | Telegram API ID for MTProto identity lookups. The bot refuses to boot without it. |
| `API_HASH` | Yes | string | Telegram API hash matching `API_ID`. Never commit the real value. |
| `MTPROTO_SESSION` | No | string | Namespace for the shared MTProto session in PostgreSQL. Default `tcbot_mtproto`. |
| `LOG_LEVEL` | No | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` | Runtime logging level. Default `INFO`. |
| `MODULES_LOAD` | No | comma-separated module names | Optional allowlist, e.g. `bans,appeals`. |
| `MODULES_NO_LOAD` | No | comma-separated module names | Optional denylist, e.g. `maintenance,broadcast`. |
| `REDIS_URL` | No | Redis URI | L2 cache connection string, e.g. `redis://localhost:6379/0`. When absent the bot uses in-process L1 cache only. |
| `DB_POOL_SIZE` | No | integer >= 1 | Size of the PostgreSQL connection pool. Default `5`. Keep the total (`DB_POOL_SIZE` + `DB_MAX_OVERFLOW`) within the connection limit the database grants the bot user: a pooler in transaction or session mode caps it, and an oversized pool fails later as a "max clients reached" refusal that the circuit breaker reads as a database outage. |
| `DB_MAX_OVERFLOW` | No | integer >= 0 | Extra connections the pool may open beyond `DB_POOL_SIZE` under load. Default `5`. These connections are closed again once the load drops. |
| `DB_SCHEMA` | No | PostgreSQL identifier | The schema the bot reads and writes. Default `public`. The project uses three schemas and no more: `public` for the deployment, `test` for the integration tests, and `development` for a developer working against a shared server. A schema that does not exist yet is created at startup. |
| `SENTRY_DSN` | No | DSN string | Error monitoring via Sentry (observability extra: install `tcbot[observability]`). When empty, monitoring is disabled. |
| `WEBHOOK_URL` | No | URL | Base URL for webhook transport, e.g. `https://yourdomain.example.com`. An explicit value takes precedence over the automatically detected `REPLIT_DEV_DOMAIN`; when neither is available, the bot falls back to polling for local development. The dev domain is only used when the bot runs as the Replit application, so a workspace shell that starts the bot by hand polls instead of registering a webhook another process would receive. |
| `WEBHOOK_SECRET` | No | random string | Secret token sent in the `X-Telegram-Bot-Api-Secret-Token` header by Telegram on every webhook POST. Auto-generated with `secrets.token_hex(32)` if absent. Set it explicitly for a stable deployment token. |
| `CRON_SECRET` | Yes on Vercel | random string | Bearer token for the serverless warn-expiry cron endpoint. Requests without a matching token fail closed (`401`/`503`). |
| `WARN_LIMIT` | No | integer >= 1 | Per-group warning threshold that triggers automatic federation ban. Default `3`. When a user's warn count in one group reaches or exceeds this value, they are federation-banned and their group warns cleared (on success). |
| `FED_WARN_LIMIT` | No | integer >= 0 | Federation-wide warning threshold: sum of warn counts across all groups triggers an automatic federation ban when >= this value. Default `0` (disabled). Set to a positive integer to enable cross-group warn aggregation. |
| `WARN_EXPIRY_DAYS` | No | positive integer | Days after which warning decisions expire and stop counting towards the auto-ban threshold. Default `0` (disabled). Set to a positive integer to enable automatic warn expiry. |
| `COMMUNITY_CHANNEL_URL` | No | http(s) URL | Main Channel button in the Additional Links menu. Built-in default `https://t.me/TranssionCoreFederation`. |
| `COMMUNITY_GROUP_URL` | No | http(s) URL | Discussion Group button. Built-in default `https://t.me/TranssionCoreFederationGroup`. |
| `COMMUNITY_LOGS_URL` | No | http(s) URL | Logs Channel button. Built-in default `https://t.me/TranssionCoreFederationLogs`. |
| `COMMUNITY_APPEAL_URL` | No | http(s) URL | Appeals Channel button. Built-in default `https://t.me/TranssionCoreFederationAppeals`. |
| `COMMUNITY_TRAVEL_URL` | No | http(s) URL | TRAVEL community button. Built-in default `https://t.me/+S2C_ppFvHlAwMzNl`. |

Each community link falls back to its built-in default when empty, so all five buttons show with zero setup. A non-http(s) value is ignored with a warning and hides that button.

MTProto runs on the bot token alone: no phone number, no login code, no
session file. Fill `API_ID` / `API_HASH` and boot connects a bot-token
session automatically; lookups keep working with zero manual steps.

Run exactly one live long-lived instance at a time. The MTProto session
is shared, but Telegram kills the auth key when two clients connect with
it at once (`406 AUTH_KEY_DUPLICATED`): instances elect a single owner
through a short-lived lease, and losers serve Bot-API-only until the
lease frees up. Overlapping rolling restarts are safe (the old instance
releases on shutdown and the newcomer takes over an expired lease), but
a Replit deploy plus a GitHub runner side by side is not: stop one of
them. If the key is already invalidated (either `406 AUTH_KEY_DUPLICATED`
from a duplicate connection or transport `404 AUTH_KEY_NOT_FOUND` when
Telegram reports the key is gone), stop every instance, purge the
session rows (`DELETE FROM mtproto_state WHERE id LIKE '<MTPROTO_SESSION>:%'`),
then boot exactly one instance and the bot-token login
mints a fresh key automatically. The bot token itself never needs
rotating for this incident. The bot parks MTProto and stays on
Bot-API-only until the purge and reboot, so moderation never goes
offline over this dead key.

## Startup sequence

1. `tcbot.__init__` loads configuration into `cfg` and fails fast when `BOT_TOKEN`, `DATABASE_URL`, or `OWNER_ID` are missing.
2. `tcbot.__main__.main()` configures logging.
3. `tcbot.alive.start_keepalive()` starts Flask on `0.0.0.0:PORT`.
4. PTB `ApplicationBuilder` builds the bot application.
5. `tcbot.modules.get_handlers()` imports active modules and stops startup if an enabled module fails to import.
6. Signal handlers (`SIGTERM`, `SIGINT`) are registered immediately before the PTB lifecycle begins.
7. `_post_init()` connects PostgreSQL (applying the pending schema migrations first), seeds the initial owner, connects the optional Redis cache, starts the APScheduler, connects MTProto (bot-token session; missing `API_ID`/`API_HASH` aborts boot), and attaches the error reporter.
8. **Webhook mode** (when `WEBHOOK_URL` is set, or `REPLIT_DEV_DOMAIN` resolves to a URL and this process is the Replit application): `bot.set_webhook()` registers the URL, `register_webhook()` wires Flask's `POST /webhook` to PTB's update queue, and the bot waits for `SIGTERM`/`SIGINT`.
9. **Polling mode** (when no webhook URL is available): `run_polling()` starts with `drop_pending_updates=True`. A `WARNING` log identifies this local-development fallback.

## Troubleshooting

### `BOT_TOKEN is required but not set`

Set `BOT_TOKEN` in `config.env` or the host secret manager.

### `OWNER_ID is required and must be a positive integer`

Set `OWNER_ID` to your numeric Telegram user ID, not a username.

### `DATABASE_URL is required but not set`

Set `DATABASE_URL` in `config.env` or the host secret manager. Do not paste real connection strings into logs or documentation.

### PostgreSQL connection failure

Check `DATABASE_URL`, network access, the host firewall, and the database credentials. The bot applies its schema migrations at startup, so the role also needs permission to create tables in the target database.

### PostgreSQL `CERTIFICATE_VERIFY_FAILED` (`unable to get local issuer certificate`)

The host's system CA store is empty or outdated, so the server TLS chain cannot be verified. Point the driver at a usable bundle with `?sslrootcert=/path/to/ca.pem` in `DATABASE_URL`, or install the system CA package. Never disable TLS verification to work around this.

### `Module import failed for: ...`

Check the named module's import traceback, missing dependencies, and top-level syntax before redeploying. Enabled modules should fail loudly rather than being skipped silently.

### A command does nothing

Check:

- The module is not blocked by `MODULES_NO_LOAD`.
- `MODULES_LOAD` is empty or includes the module filename without `.py`.
- The command prefix is included in `PREFIXES`.
- The module exposes a non-empty `__handlers__` list.

### Buttons stop responding

Check callback patterns in the registering module, then inspect `tcbot/modules/helper/keyboards/` and the matching callback handler.
