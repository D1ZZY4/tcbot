# Replit Environment — TCF Bot

## Workflow

- **Name:** `Start application`
- **Command:** `python3 -m tcbot`
- Restart after any code or dependency change.

## Port

Flask keepalive runs on port `5000` (configurable via `PORT` in `config.env`).
The bot itself uses long polling — no webhook, no extra port needed.

## Environment Variables

Secrets are stored in **Replit Secrets** (environment variables), not in `config.env`.
Non-sensitive config is in `.replit` `[userenv.shared]`.
`config.env` is gitignored and kept only as a local fallback — never commit it.
See `config.env.example` for the full list of required keys.

Key variables:
| Variable | Storage | Description |
|---|---|---|
| `BOT_TOKEN` | Replit Secret | Telegram bot token |
| `MONGODB_URI` | Replit Secret | MongoDB connection string |
| `OWNER_ID` | Replit env var | Telegram user ID of the federation owner |
| `DB_NAME` | Replit env var | MongoDB database name (default: `tcbot`) |
| `LOGS` | Replit env var | Log channel chat ID (optionally `chat_id/thread_id`) |
| `PROOFS` | Replit env var | Proof channel chat ID |
| `APPEALS` | Replit env var | Appeal channel chat ID |
| `PROOF_TIMEOUT_SECONDS` | Replit env var | ConversationHandler timeout for ban proof step |
| `APPEAL_TIMEOUT_SECONDS` | Replit env var | ConversationHandler timeout for appeal flow |

## Dependencies

Managed via `pyproject.toml` + `uv.lock`. Install with:
```
pip install -r requirements.txt
```

Core deps: `python-telegram-bot[all]==22.5`, `motor`, `flask`, `python-dotenv`, `apscheduler`

## MongoDB

Motor (async) client. Connection is established in `tcbot/database/mongos.py` via `connect()`,
called during bot startup in `__main__.py`. The client is a module-level singleton.

## Logs

Structured log format: `[HH:MM] [DD-MM-YYYY] | <community_name> | <L> - <module>:<line> - <msg>`

Log level: `INFO` by default. Set `logging.DEBUG` in `utils/logger.py` for verbose output.
Third-party loggers (httpx, telegram, motor, pymongo) are capped at WARNING.
