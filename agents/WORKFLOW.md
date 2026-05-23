# Development Workflow — TCF Bot

**Read `agents/CLAUDE.md` first.** This file defines branching strategy, commit conventions, and the deployment checklist.

Compatible with: Replit AI, Claude, Gemini, Qwen, GitHub Copilot, and any AI coding agent.

---

## Before Making Any Change

1. Read the full content of the file you are about to edit.
2. Check for duplicate logic across modules before adding a new function.
3. If you are changing a database schema (adding or removing fields), update all read paths too.
4. Run `python3 -m pytest tests/ -v` — all 121 tests must pass before you start.

---

## Branching Strategy

| Branch | Purpose |
|---|---|
| `main` | Production-ready code only. Never push broken code here. |
| `feat/<short-description>` | New features |
| `fix/<short-description>` | Bug fixes |
| `refactor/<short-description>` | Refactors and code quality improvements |
| `docs/<short-description>` | Documentation-only changes |

Merge to `main` only after the bot starts without any `ERROR` in startup logs.

---

## Making Changes

### Before editing a file

1. Read the entire file to understand what already exists.
2. Confirm no equivalent function already exists elsewhere.
3. Confirm the change does not break the 3-layer decorator stack.

### After editing a file

1. Run the full test suite: `python3 -m pytest tests/ -v`
2. Restart the `Start application` workflow.
3. Check startup logs for import errors.
4. If touching a handler, verify the relevant command works in Telegram.

---

## Adding a New Command Module

1. Create `tcbot/modules/<name>.py`
2. Add the copyright header, `from __future__ import annotations`, and the module docstring
3. Set `__module_name__` and `__help_text__`
4. Implement the command entry point with the 3-layer decorator stack
5. Expose `__handlers__ = [...]` at the bottom
6. If the module needs priority ordering, add it to `_PRIORITY_FIRST` or `_PRIORITY_LAST` in `modules/__init__.py`

Module template:

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
__help_text__   = "<b>Commands</b>\n<code>/mycommand</code>\n\n..."


# ────────────────────────── Command ──────────────────────────────── #

@decorators.ratelimiter(limit=5, period=60)
@decorators.mod_only
@decorators.log_execution
async def cmd_example(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    ...


# ─────────────────────────── Handlers ───────────────────────────── #

_MYCOMMAND_CMDS = build_prefixed_filters("mycommand")

__handlers__ = [MessageHandler(_MYCOMMAND_CMDS, cmd_example)]
```

---

## Adding a Database Collection

1. Create `tcbot/database/<name>_db.py`
2. Add a private `_col()` accessor: `return col("<collection_name>")`
3. Implement all helpers as `async def` with full type annotations
4. Add the collection's indexes to `mongos.ensure_indexes()` in `tcbot/database/mongos.py`
5. Export the module from `tcbot/database/__init__.py`

---

## Adding a ConversationHandler Flow

**Never create `*_conv.py` files.** All flows live in `*_flow.py` files.

For kick / mute / warn — add an executor adapter and call `reason_flow.build_modaction_conv()`:

```python
# myaction_flow.py
from tcbot.modules.helper.workflows.reason_flow import (
    WAITING_REASON, WAITING_PROOF, build_modaction_conv,
)

async def _exec_myaction(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE,
    target_id: int, target_fname: str, reason: str, proof_desc: str | None,
    executor_id: int, executor_fname: str,
) -> None:
    ...  # your executor logic

def myaction_conversation(entry_fn) -> ConversationHandler:
    return build_modaction_conv(
        action="myaction",
        entry_fn=entry_fn,
        executor=_exec_myaction,
        entry_filter=build_prefixed_filters("tcmyaction"),
    )
```

For ban — add an entry function and call `ban_flow.ban_conversation(entry_fn)`.
For a completely new flow — model it after `appeal_flow.py` (standalone state graph).

---

## Commit Messages

Use conventional commits:

```
feat: add /tcsweep command with SweepAgent
fix: remove dead bans variable in connected_flow
refactor: deduplicate _render() between start.py and groups.py
chore: modernize typing hints to Python 3.12 built-ins
docs: rewrite agents/CLAUDE.md with full architecture detail
test: add rate-limiter edge cases for concurrent callers
```

---

## Deployment Checklist

Before any merge to `main`:

- [ ] All 121 tests pass: `python3 -m pytest tests/ -v`
- [ ] Bot starts without any `ERROR` in startup logs
- [ ] MongoDB connection confirmed in logs: `MongoDB connected → <db_name>`
- [ ] Keep-alive Flask confirmed in logs: `Flask keepalive started on port 8080`
- [ ] `/start` shows the main menu in bot PM
- [ ] `/help` lists all expected modules
- [ ] At least one moderation command tested end-to-end in a connected group
- [ ] `config.env` does not contain any real secrets (secrets are in Replit Secrets)

---

## Related Documentation

- [Architecture](../docs/architecture.md)
- [Modules](../docs/modules.md)
- [Conversation flows](../docs/workflows.md)
- [Development onboarding](../docs/development.md)
