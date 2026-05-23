# Development Workflow and Onboarding — TCF Bot

This document covers local setup, onboarding for new engineers, and step-by-step guides for common development tasks.  
For architecture details, see [docs/architecture.md](architecture.md).  
For agent and coding conventions, see [agents/CLAUDE.md](../agents/CLAUDE.md).

---

## Prerequisites

- Python 3.13
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

# 4. Run the tests to verify your setup
python3 -m pytest tests/ -v

# 5. Start the bot
python3 -m tcbot
```

Expected startup log output:

```
[HH:MM] [DD-MM-YYYY] | TCF | I - __main__:XX - Flask keepalive started on port 5000
[HH:MM] [DD-MM-YYYY] | TCF | I - mongos:XX - MongoDB connected → tcbot
[HH:MM] [DD-MM-YYYY] | TCF | I - __main__:XX - Handlers registered: XX handlers
[HH:MM] [DD-MM-YYYY] | TCF | I - __main__:XX - Bot started. Polling...
```

If you see `ERROR` anywhere in startup, stop and fix the issue before testing.

---

## Replit Setup

On Replit, secrets are stored in Replit Secrets — not `config.env`:

| Secret | Where to set |
|---|---|
| `BOT_TOKEN` | Replit Secrets panel |
| `MONGODB_URI` | Replit Secrets panel |

All other variables are set as Replit environment variables. See `agents/REPLIT.md` for the complete list.

The `Start application` workflow runs `python3 -m tcbot`. Use the Replit Run button or the Workflows panel to start/restart.

---

## Configuration Reference

See `config.env.example` for the full list with descriptions. The most important fields:

| Variable | Required | Description |
|---|---|---|
| `BOT_TOKEN` | Yes | Bot token from @BotFather |
| `OWNER_ID` | Yes | Your Telegram user ID (becomes the Founder) |
| `MONGODB_URI` | Yes | MongoDB connection string |
| `DB_NAME` | No | Database name (default: `tcbot`) |
| `MAIN_GROUP` | Yes | Telegram chat ID of the main group/forum |
| `LOGS` | Yes | Log channel: `chat_id` or `chat_id/thread_id` |
| `PROOFS` | Yes | Proof channel: `chat_id` or `chat_id/thread_id` |
| `APPEALS` | Yes | Appeal record channel: `chat_id` or `chat_id/thread_id` |
| `APPEAL_DISCUSSION_TOPIC` | Yes | Thread ID inside `MAIN_GROUP` for appeal review |

---

## Running Tests

```bash
python3 -m pytest tests/ -v
```

All 121 tests run fully offline — no bot token or MongoDB required. Run after every code change.

| Test file | What it covers |
|---|---|
| `test_format.py` | `parse_link` HTML helpers |
| `test_targets.py` | `ResolvedTarget` and `get_reason` |
| `test_users_resolver.py` | `resolve_identity` with mocked repos |
| `test_prefix.py` | Alt-prefix dispatcher and registry |
| `test_keyboards.py` | Keyboard factory output shapes |
| `test_decorators.py` | `log_execution` tracer |
| `test_appeals_pure.py` | Pure appeal guard functions |
| `test_log_templates.py` | Log message formatters |
| `test_rate_limiter.py` | `_RateLimiter` sliding-window logic |

---

## Adding a New Command Module

1. Create `tcbot/modules/<name>.py` with the standard header:

```python
# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""One-line description of what this module does."""

from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes, MessageHandler

from tcbot.modules.helper import decorators
from tcbot.utils.prefixes import build_prefixed_filters

log = logging.getLogger(__name__)


__module_name__ = "MyModule"
__help_text__   = (
    "<b>Commands & Aliases</b>\n"
    "<code>/mycommand</code>\n\n"
    "..."
)
```

2. Implement the handler with the 3-layer decorator stack:

```python
@decorators.ratelimiter(limit=5, period=60)
@decorators.mod_only
@decorators.log_execution
async def cmd_mycommand(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    admin = update.effective_user
    ...
```

3. Define command filters and export `__handlers__` at the bottom (use `*_CMDS` naming, as in `admins.py`):

```python
_MYCOMMAND_CMDS = build_prefixed_filters("mycommand")

__handlers__ = [
    MessageHandler(_MYCOMMAND_CMDS, cmd_mycommand),
]
```

4. If the module needs priority ordering (e.g. must run before or after conversation handlers), add it to `_PRIORITY_FIRST` or `_PRIORITY_LAST` in `modules/__init__.py`.

5. Run the tests and restart the bot to verify discovery.

---

## Adding a New Database Collection

1. Create `tcbot/database/<name>_db.py`:

```python
# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""<Collection name> collection helpers."""

from __future__ import annotations

from tcbot.database.mongos import col


def _col():
    return col("<collection_name>")


async def get_by_user(user_id: int) -> dict | None:
    return await _col().find_one({"user_id": user_id})


async def upsert(user_id: int, data: dict) -> None:
    await _col().update_one(
        {"user_id": user_id},
        {"$set": {"user_id": user_id, **data}},
        upsert=True,
    )
```

2. Add indexes to `mongos.ensure_indexes()`:

```python
# In mongos.py, inside ensure_indexes():
col("<collection_name>").create_index("user_id", background=True),
```

3. Export from `tcbot/database/__init__.py`:

```python
from tcbot.database import <name>_db  # noqa: F401
```

---

## Adding a ConversationHandler Flow

**For kick / mute / warn style (reason + proof):**

Create `tcbot/modules/helper/workflows/<name>_flow.py`:

```python
from tcbot.modules.helper.workflows.reason_flow import (
    WAITING_REASON, WAITING_PROOF, build_modaction_conv,
)
from tcbot.utils.prefixes import build_prefixed_filters

async def execute_<name>(
    update, ctx, target_id, target_fname, reason, proof_desc,
    executor_id, executor_fname,
) -> None:
    ...  # your action logic

async def _exec_<name>(update, ctx, **kw) -> None:
    await execute_<name>(update, ctx, **kw)

def <name>_conversation(entry_fn, entry_filter):
    return build_modaction_conv(
        reason, proof, entry_fn, _exec_<name>, entry_filter,
    )
```

Then in your module file:

```python
from tcbot.modules.helper.workflows.<name>_flow import <name>_conversation
from tcbot.utils.prefixes import build_prefixed_filters

@decorators.ratelimiter(limit=5, period=60)
@decorators.basic_mod_only
@decorators.log_execution
async def cmd_<name>_start(update, ctx):
    ...
    return WAITING_REASON   # or WAITING_PROOF or ConversationHandler.END

_<NAME>_CMDS = build_prefixed_filters("tc<name>")

__handlers__ = [<name>_conversation(cmd_<name>_start, _<NAME>_CMDS)]
```

**For ban style (proof only, album support):** model after `banning.py` + `ban_flow.py`.

**For a completely standalone flow:** model after `appeal_flow.py`.

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

## Related Documentation

- [Architecture and startup flow](architecture.md)
- [Modules and service boundaries](modules.md)
- [Conversation flows](workflows.md)
- [AI agent instructions](../agents/CLAUDE.md)
- [Project rules](../agents/RULES.md)
- [Execution plan and bug tracker](../PLAN.md)
