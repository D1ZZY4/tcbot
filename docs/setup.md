# SETUP GUIDELIES - TCF Bot

This document covers local setup, onboarding for new engineers, and step-by-step guides for common development tasks.

---

## Prerequisites

- Python 3.12
- `uv` package manager (`pip install uv` or https://docs.astral.sh/uv)
- A MongoDB instance (local, Docker, or Atlas)
- A Telegram bot token (from @BotFather)
- A Telegram group/channel set up for logs, proofs, and appeals

---

## Local Setup

```bash
# 1. Clone the repo
git clone <repo-url>
cd tcf-bot

# 2. Install dependencies
uv sync

# 3. Configure the environment
cp config.env.example config.env
# Open config.env and fill in all required values (see Configuration Reference below)

# 4. Start the bot
python3 -m tcbot

# 5. Run the tests to verify your setup (Optional)
python3 -m pytest tests/ -v
```

Expected startup log output:

```
[HH:MM] [DD-MM-YYYY] [INFO] [__main__:XX] → Flask keepalive started on port 5000
[HH:MM] [DD-MM-YYYY] [INFO] [mongos:XX] → MongoDB connected → tcbot
[HH:MM] [DD-MM-YYYY] [INFO] [__main__:XX] → Handlers registered: XX handlers
[HH:MM] [DD-MM-YYYY] [INFO] [__main__:XX] → Bot started. Polling...
```

If you see `ERROR` anywhere in startup, stop and fix the issue before testing.

---

## Replit Setup

On Replit, secrets are stored in Replit Secrets - not `config.env`:

| Secret | Where to set |
|---|---|
| `BOT_TOKEN` | Replit Secrets panel |
| `MONGODB_URI` | Replit Secrets panel |

All other variables are set as Replit environment variables. See `agents/REPLIT.md` for the complete list.

The `Start Application` workflow runs `python3 -m tcbot`. Use the Replit Run button or the Workflows panel to start/restart.

---

## Docker Development

```bash
# Start bot + MongoDB
docker-compose up --build

# Rebuild after dependency changes
docker-compose up --build --force-recreate

# View logs
docker-compose logs -f bot
```

The compose file uses `mongo:7` and a health-check that waits for MongoDB before starting the bot.

---

## Common Debugging

### Import error at startup

The bot fails immediately with a traceback pointing to a module file.

1. Read the traceback — it always names the exact file and line.
2. Check imports: are all referenced modules actually installed (`uv sync`)? Are internal imports spelled correctly?
3. Check for `*_conv.py` files — these should not exist; ConversationHandlers belong in `*_flow.py`.

### Handler not registered

A command does nothing.

1. Check that the module is not in `MODULES_NO_LOAD`.
2. Check that `__handlers__` is defined and non-empty.
3. Check that the `MessageFilter` or `CommandHandler` pattern matches the command prefix.
4. Restart the bot workflow.

### MongoDB not connecting

Startup log shows `ERROR` at the MongoDB connect step.

1. Verify `MONGODB_URI` is correct and the database is reachable.
2. Check IP allowlist on MongoDB Atlas (add `0.0.0.0/0` for development).
3. On Replit: confirm `MONGODB_URI` is in Replit Secrets, not `config.env`.

### Rate limiter blocking all users

Every command returns a rate-limit message.

1. Check that `ratelimiter(limit, period)` values are reasonable (not `limit=1, period=3600`).
2. Confirm `@ratelimiter` is the outermost decorator.
3. Check the global rate limiter in `__main__.py` — `global_rate_limit_handler` applies a coarser throttle for all commands.

---