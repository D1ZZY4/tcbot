# Setup Guide

This guide explains how to run TCF Bot locally, with Docker, or in a hosted environment without committing secrets.

## Prerequisites

- Python 3.12 or newer. The project metadata targets `>=3.12`.
- [`uv`](https://docs.astral.sh/uv/) for dependency and lockfile management.
- A Telegram bot token from BotFather.
- A MongoDB deployment, local or hosted.
- Telegram destination chats for logs, errors, proofs, and appeals.

## Local setup

```bash
git clone <repo-url>
cd tgbot
uv sync
cp config.env.example config.env
python -m tcbot
```

Use `python3 -m tcbot` if your platform exposes Python as `python3`.

Run the offline test suite:

```bash
uv run --extra test pytest tests/ -v
```

Format and lint after edits:

```bash
uv run ruff format .
uv run ruff check --fix .
```

## Docker setup

The repository includes a Docker Compose stack with the bot and `mongo:7`.

```bash
docker-compose up --build
```

The `bot` service reads `config.env`, exposes port `5000`, and waits for the MongoDB health check before startup. The image runs:

```bash
uv run --frozen python -m tcbot
```

## Hosted setup

For Replit or another hosting platform:

1. Store `BOT_TOKEN` and `MONGODB_URI` in the platform secret manager.
2. Store non-secret runtime values as environment variables.
3. Start the bot with `python -m tcbot` or `python3 -m tcbot`.
4. Make sure the Flask health endpoint port matches `PORT`.

Do not commit a filled `config.env` file.

## Environment variable format

The configuration loader reads environment variables in `tcbot/__init__.py`. Local development uses `python-dotenv` to load `config.env`.

Recommended `config.env` syntax:

```env
BOT_TOKEN="<telegram-bot-token>"
OWNER_ID="123456789"
MONGODB_URI="mongodb+srv://<user>:<password>@<cluster>/<options>"
DB_NAME="tcbot"
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
| `MONGODB_URI` | Yes | MongoDB URI | Motor connection string. Never commit it. |
| `DB_NAME` | No | string | MongoDB database name. Defaults to `tcbot`. |
| `COMMUNITY_NAME` | No | string | Display name in messages and logs. Defaults to `Bot`. |
| `PREFIXES` | No | Python-style list or CSV | Command prefixes. Default is `["/", "!", "."]`. |
| `PORT` | No | integer or `auto` | Flask keep-alive port. `auto`, invalid, or out-of-range values resolve to `5000`. |
| `MAIN_GROUP` | Usually | integer chat ID | Main community group or forum. |
| `MAIN_CHANNEL` | No | integer chat ID | Optional announcement channel reference. |
| `EXTEND_GROUP` | No | integer chat ID | Secondary group watched by selected handlers. |
| `PROOFS` | Yes for bans | `chat_id` or `chat_id/thread_id` | Destination for ban proof media. |
| `LOGS` | Yes | `chat_id` or `chat_id/thread_id` | Audit-log destination. |
| `LOGS_ERRORS` | Recommended | `chat_id` or `chat_id/thread_id` | Error-report destination. |
| `APPEALS` | Yes for appeals | `chat_id` or `chat_id/thread_id` | Submitted appeal record destination. |
| `APPEAL_LOG_HANDLE` | No | channel handle | Displayed in appeal instructions. Defaults to `@TranssionCoreFederationLogs`. |
| `APPEAL_DISCUSSION_TOPIC` | Yes for reviews | integer thread ID | Topic inside `MAIN_GROUP` where review cards are posted. |
| `PROOF_TIMEOUT_SECONDS` | No | integer seconds | Ban proof conversation timeout. Default `100`; values below `1` fall back to default. |
| `APPEAL_TIMEOUT_SECONDS` | No | integer seconds | Appeal conversation timeout. Default `600`; values below `1` fall back to default. |
| `ALBUM_DEBOUNCE_SECONDS` | No | integer seconds | Album buffering window for ban proof media. Default `2`; values below `1` fall back to default. |
| `LOG_LEVEL` | No | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` | Runtime logging level. Default `INFO`. |
| `MODULES_LOAD` | No | comma-separated module names | Optional whitelist, e.g. `banning,appeals`. |
| `MODULES_NO_LOAD` | No | comma-separated module names | Optional blacklist, e.g. `maintenance,broadcasting`. |

## Startup sequence

1. `tcbot.__init__` loads configuration into `cfg` and fails fast when `BOT_TOKEN`, `MONGODB_URI`, or `OWNER_ID` are missing.
2. `tcbot.__main__.main()` configures logging.
3. `tcbot.alive.start_keepalive()` starts Flask on `0.0.0.0:PORT`.
4. PTB `ApplicationBuilder` builds the bot application.
5. `tcbot.modules.get_handlers()` imports active modules and stops startup if an enabled module fails to import.
6. `_post_init()` connects MongoDB, ensures indexes, seeds the initial owner, and attaches the error reporter.
7. Long polling starts with `drop_pending_updates=True`.

## Troubleshooting

### `BOT_TOKEN is required but not set`

Set `BOT_TOKEN` in `config.env` or the host secret manager.

### `OWNER_ID is required and must be a positive integer`

Set `OWNER_ID` to your numeric Telegram user ID, not a username.

### `MONGODB_URI is required but not set`

Set `MONGODB_URI` in `config.env` or the host secret manager. Do not paste real connection strings into logs or documentation.

### MongoDB connection failure

Check `MONGODB_URI`, network access, Atlas IP allowlists, and database credentials.

### `Module import failed for: ...`

Check the named module's import traceback, missing dependencies, and top-level syntax before redeploying. Enabled modules should fail loudly rather than being skipped silently.

### A command does nothing

Check:

- The module is not blocked by `MODULES_NO_LOAD`.
- `MODULES_LOAD` is empty or includes the module filename without `.py`.
- The command prefix is included in `PREFIXES`.
- The module exposes a non-empty `__handlers__` list.

### Buttons stop responding

Check callback patterns in the registering module, then inspect `tcbot/modules/helper/keyboards.py` and the matching callback handler.
