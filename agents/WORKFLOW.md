# Development Workflow — TCF Bot

**Read `agents/CLAUDE.md` first.** This file defines branching strategy, commit conventions, and the deployment checklist.

Compatible with: Replit AI, Claude, Gemini, Qwen, GitHub Copilot, and any AI coding agent.

---

## Before Making Any Change

1. Read the full content of the file you are about to edit.
2. Check for duplicate logic across modules before adding a new function.
3. If you are changing a database schema (adding or removing fields), update all read paths too.
4. Run `python3 -m pytest tests/ -v` — all 134 tests must pass before you start.

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

- [ ] All 134 tests pass: `python3 -m pytest tests/ -v`
- [ ] Bot starts without any `ERROR` in startup logs
- [ ] MongoDB connection confirmed in logs: `MongoDB connected → <db_name>`
- [ ] Keep-alive Flask confirmed in logs: `Flask keepalive started on port 5000`
- [ ] `/start` shows the main menu in bot PM
- [ ] `/help` lists all expected modules
- [ ] At least one moderation command tested end-to-end in a connected group
- [ ] `config.env` is gitignored and not committed to version control

---