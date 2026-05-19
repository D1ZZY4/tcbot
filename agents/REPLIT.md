# Replit Agent Instructions and Environment Configuration - TCF Bot

## Workflow

- **Name:** `Start application`
- **Command:** `python3 -m tcbot`
- Restart after any code or dependency change.

## Port

Flask keepalive runs on port `5000` (configurable via `PORT` in `config.env`).
The bot itself uses long polling - no webhook, no extra port needed.

## Environment Variables

**All configuration - including secrets - is stored exclusively in `config.env`.**
Do NOT use Replit Secrets for this project. Do NOT commit `config.env` (it is gitignored).
See `config.env.example` for the full list of required keys.

Key variables:
| Variable | Storage | Description |
|---|---|---|
| `BOT_TOKEN` | `config.env` | Telegram bot token |
| `MONGODB_URI` | `config.env` | MongoDB connection string |
| `OWNER_ID` | `config.env` | Telegram user ID of the federation owner |
| `DB_NAME` | `config.env` | MongoDB database name (default: `tcbot`) |
| `LOGS` | `config.env` | Log channel chat ID (optionally `chat_id/thread_id`) |
| `PROOFS` | `config.env` | Proof channel chat ID |
| `APPEALS` | `config.env` | Appeal channel chat ID |
| `PROOF_TIMEOUT_SECONDS` | `config.env` | ConversationHandler timeout for ban proof step |
| `APPEAL_TIMEOUT_SECONDS` | `config.env` | ConversationHandler timeout for appeal flow |

## Dependencies

Managed via `pyproject.toml` + `uv.lock`. Install with:
```
uv sync
```

Core deps: `python-telegram-bot[all]==22.5`, `motor`, `flask`, `python-dotenv`, `apscheduler`

## MongoDB

Motor (async) client. Connection is established in `tcbot/database/mongos.py` via `connect()`,
called during bot startup in `__main__.py`. The client is a module-level singleton.

## Logs

Structured log format: `[HH:MM] [DD-MM-YYYY] | <community_name> | <L> - <module>:<line> - <msg>`

Log level: `INFO` by default. Set `logging.DEBUG` in `utils/logger.py` for verbose output.
Third-party loggers (httpx, telegram, motor, pymongo) are capped at WARNING.

## Related documentation

- [Documentation hub](../docs/index.md)
- [Project architecture](../docs/architecture.md)
- [Modules and service boundaries](../docs/modules.md)
- [Conversation flows and workflows](../docs/workflows.md)
- [Development workflow and onboarding](../docs/development.md)
- [AI / agent guidelines](../docs/agent-guidelines.md)
