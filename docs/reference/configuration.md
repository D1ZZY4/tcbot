# Configuration

Configuration is loaded once from environment variables by
`tcbot/__init__.py`. For local development `python-dotenv` loads `config.env`,
falling back to `.env`. The immutable `Configs` model is built on first access,
so importing submodules never requires credentials. Invalid required values
fail at load time with an actionable message. The template is
`config.env.example`.

## Required values

| Variable | Default | Notes |
|---|---|---|
| `BOT_TOKEN` | none | Telegram bot token. A malformed shape logs a warning but is not rejected here. |
| `DATABASE_URL` | none | PostgreSQL connection string. `postgres://`, `postgresql://`, and `postgresql+psycopg://` are accepted. |
| `OWNER_ID` | none | Positive integer Telegram user id of the initial Owner. |
| `PROOFS` | none | Negative group or channel id; `chat_id/thread_id` is accepted. Boot refuses a missing or positive value. |
| `API_ID` | `0` | Telegram API id. Boot refuses a missing or zero value in `__main__.py`. |
| `API_HASH` | empty | Telegram API hash matching `API_ID`. Boot refuses a missing or empty value together with `API_ID`. |

## Runtime and transport

| Variable | Default | Notes |
|---|---|---|
| `COMMUNITY_NAME` | `Bot` | Display name in messages and logs. |
| `PREFIXES` | `["/", "!", "."]` | Python-style list or tuple, or comma-separated values. |
| `PORT` | `5000` | Blank, invalid, or out-of-range values resolve to 5000. Keep it numeric under Compose, which maps the same value from the host. |
| `BIND_HOST` | `0.0.0.0` | Listener interface; `127.0.0.1` behind a reverse proxy. |
| `LOG_LEVEL` | `INFO` | `NOTSET`, `DEBUG`, `INFO`, `WARNING`, `WARN`, `ERROR`, `CRITICAL`, `FATAL`. |
| `SENTRY_DSN` | empty | Opt-in error monitoring with the observability extra. |
| `KURIGRAM_WORKERS` | `0` (automatic) | Dispatcher worker count. Automatic sizing uses CPU count and the database pool, capped at 64; it improves throughput under load, not single-update latency. |
| `MODULES_LOAD` | empty | Python-style list or tuple, or comma-separated allowlist of module names. |
| `MODULES_NO_LOAD` | empty | Python-style list or tuple, or comma-separated denylist of module names. |

## Destinations

| Variable | Default | Notes |
|---|---|---|
| `MAIN_GROUP` | unset | Primary community group id; must be negative. A positive value is treated as unset. |
| `MAIN_CHANNEL` | unset | Main community channel behind the menu link; must be negative. A positive value is treated as unset. |
| `LOGS` | unset | Federation log destination. |
| `LOGS_ERRORS` | unset | Separate error destination; falls back to the Owner DM when empty. |
| `APPEALS` | unset | Appeal destination. |
| `INFRA_CHAT_IDS` | `[]` | Extra deployment-owned chat ids refused by the connect paths; list, tuple, or CSV, negative ids only. |

`PROOFS`, `LOGS`, `LOGS_ERRORS`, and `APPEALS` accept `chat_id` or
`chat_id/thread_id`. A thread id must be positive; a non-positive segment is
dropped. `MAIN_GROUP` and `MAIN_CHANNEL` take a plain negative chat id only: a
thread suffix is invalid there and resolves to the unset value. Community menu
links derive from these ids through `rich/link.py`; no static URL variables
remain.

## Database and cache

| Variable | Default | Notes |
|---|---|---|
| `DATABASE_URL` | required | See above. |
| `DB_SCHEMA` | `public` | Only `public`, `test`, and `development` are accepted; any other value falls back to `public` instead of creating a fourth schema. |
| `DB_POOL_SIZE` | `5` | Minimum 1. Must fit the server's connection limit. |
| `DB_MAX_OVERFLOW` | `5` | Minimum 0. |
| `REDIS_URL` | empty | Optional Redis L2 cache; empty runs on in-memory L1 only. |
| `PG_CRON_ENABLED` | `false` | Let pg_cron own database-only jobs when the extension exists. |
| `MTPROTO_SESSION` | `tcbot_mtproto` | Namespace for the shared MTProto session. |

## Moderation policy

| Variable | Default | Notes |
|---|---|---|
| `ALBUM_DEBOUNCE_SECONDS` | `4` | Proof silence window, minimum 1. Proof collection is independently capped at 60 seconds, so a larger value still flushes within that window. |
| `WARN_LIMIT` | `3` | Per-group warn threshold, minimum 1. |
| `WARN_EXPIRY_DAYS` | `0` | Days after which a warning stops counting toward the threshold; 0 disables expiry. Warning history is kept and never deleted. |
| `FED_WARN_LIMIT` | `0` | Federation-wide threshold; 0 disables it. |
| `PROMOTION_REQUEST_TTL_DAYS` | `7` | Pending request lifetime; 0 disables expiry. |

## Testing

| Variable | Default | Notes |
|---|---|---|
| `TCBOT_TEST_DATABASE_URL` | unset | Database used by the `postgres`-marked tests. When unset those tests skip. Use a dedicated test database, never the deployment one. |
| `TCBOT_TEST_REDIS_URL` | unset | Redis used by the Redis integration tests. When unset those tests skip. Use a dedicated test instance, never the deployment cache. |

`POSTGRES_USER`, `POSTGRES_PASSWORD`, and `POSTGRES_DB` are `docker-compose.yml`
variables, not read by the bot. Compose refuses to start the local PostgreSQL
service without an explicit `POSTGRES_PASSWORD`.

## Secrets policy

Never commit real credentials, put them in command-line arguments, or print
them to logs. `Configs` excludes token, database URL, Redis URL, API hash,
and Sentry DSN from its `repr`. Operator scripts read the connection string
from the environment rather than hardcoding it.
