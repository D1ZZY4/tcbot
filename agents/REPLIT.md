# Replit Environment — TCF Bot

**Read `agents/CLAUDE.md` and `./replit.md` first.** This file documents how the project is configured on Replit.

Compatible with: Replit AI, Claude, Gemini, Qwen, GitHub Copilot, and any AI coding agent.

---

## Workflow

- **Name:** `Start Application`
- **Command:** `python3 -m tcbot`
- This is the only workflow needed. It starts the bot, connects to MongoDB, and starts the Flask keepalive on port 8080.

To restart the bot after code changes: stop and restart the `Start Application` workflow via the Replit Run button or the Workflows panel.

---

## Secrets

Two secrets are stored in **Replit Secrets** (not in `config.env`):

| Secret | Description |
|---|---|
| `BOT_TOKEN` | Telegram bot token from @BotFather |
| `MONGODB_URI` | MongoDB connection string (Atlas or other) |

All other configuration is stored as Replit shared environment variables, set via the Replit Secrets UI (Replit Secrets can hold both secrets and general env vars).

**Never** put `BOT_TOKEN` or `MONGODB_URI` in `config.env` on Replit. These are production secrets and must stay in Replit Secrets.

---

## config.env on Replit

`config.env` is loaded as a local-dev fallback via `load_dotenv(override=False)`. On Replit, it is used only for non-sensitive config (e.g. `DB_NAME`, `COMMUNITY_NAME`, `LOGS`, `PROOFS`, `APPEALS`, `MAIN_GROUP`, etc.).

The file is gitignored and must never be committed. The template is `config.env.example`.

---

## All Other Environment Variables

The following variables are set as Replit environment variables (via the Secrets panel):

| Variable | Example | Description |
|---|---|---|
| `OWNER_ID` | `123456789` | Telegram user ID of the federation founder |
| `DB_NAME` | `tcbot` | MongoDB database name |
| `COMMUNITY_NAME` | `TCF` | Community display name used in bot messages |
| `MAIN_GROUP` | `-1001234567890` | Main group/forum chat ID |
| `MAIN_CHANNEL` | `-1009876543210` | Main channel chat ID |
| `LOGS` | `-1001111111111/2` | Log channel `chat_id` or `chat_id/thread_id` |
| `LOGS_ERRORS` | `-1001111111111/3` | Error log channel (optional) |
| `PROOFS` | `-1002222222222` | Ban proof channel |
| `APPEALS` | `-1003333333333` | Appeal record channel |
| `APPEAL_DISCUSSION_TOPIC` | `42` | Thread ID inside MAIN_GROUP for appeal review |
| `PORT` | `8080` | Flask keepalive port (Replit requires 8080) |
| `LOG_LEVEL` | `INFO` | Log verbosity |

---

## Port

The Flask keepalive server runs on port **8080** on Replit. This is the port that Replit's health-check proxy expects.

Do not change this to 5000 on Replit — Replit does not expose port 5000 externally.

The port is controlled by the `PORT` environment variable. When running locally without a `PORT` env var, it defaults to 5000.

---

## Running the Test Suite

```bash
python3 -m pytest tests/ -v
```

All 134 tests run offline — no bot token or MongoDB connection required. Run this after any code change before restarting the bot.

---

## Package Management

Dependencies are managed via `uv` and `pyproject.toml`.

- **Do not add packages to `requirements.txt`** — this file is legacy and may be gitignored.
- To add a dependency: `uv add <package>` (this updates `pyproject.toml` and `uv.lock`)
- To install for Replit: `uv sync` (already done on workflow start via the `Start Application` command setup)

---

## Local Development

For local development outside Replit, copy `config.env.example` to `config.env` and fill in all values including `BOT_TOKEN` and `MONGODB_URI`. The `load_dotenv(override=False)` call in `tcbot/__init__.py` will pick these up.

```bash
cp config.env.example config.env
# Edit config.env
uv sync
python3 -m tcbot
```

---

## Docker

A `docker-compose.yml` is provided for local development with a bundled MongoDB:

```bash
docker-compose up --build
```

The compose file starts `bot` and `mongo:7` services. The bot waits for MongoDB's health-check before connecting.