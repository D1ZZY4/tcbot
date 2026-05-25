---
created: 2026-05-25
last-modified: 2026-05-25
name: project-policy
description: >
  Enforces strict project conventions and rules for the TCBot (TCF Bot) Python Telegram bot project.
  ALWAYS use this skill before writing, editing, or generating any code for TCBot — even for small
  changes, quick fixes, refactors, or adding new features. Triggers on any code generation, file
  creation, module addition, handler registration, database interaction, import changes, or
  helper/workflow additions within the TCBot codebase. If the user mentions TCBot, tgbot_tcf,
  tcbot/, modules/, database/, utils/, handlers, flows, or anything related to the project structure,
  consult this skill immediately and before producing any output.
user-invocable: false
---

# TCBot Project Policy

Read and apply every rule below before generating or modifying any code.
When in doubt, **defer to `agents/CLAUDE.md`** — it is the canonical source of truth.

---

## Project Overview

```
(root)/
├── agents/           # ⚠️ Source of truth — read before coding
│   ├── CLAUDE.md     # Primary AI agent instructions (read first)
│   ├── RULES.md      # Hard constraints
│   ├── STYLE-CODE.md # Code style
│   ├── STYLE-COMMENTS.md  # Comment/docstring conventions
│   ├── WORKFLOW.md   # Branching, commits, deployment
│   └── REPLIT.md     # AI agent instructions for Replit environment
├── docs/             # Architecture & module documentation
├── tests/            # pytest suite (134 tests, all offline)
└── tcbot/            # Main bot package
    ├── __init__.py   # Configs dataclass + cfg singleton
    ├── __main__.py   # Startup, handler registration, polling
    ├── alive.py      # Flask keepalive (port 8080)
    ├── database/     # MongoDB layer — all writes go here
    ├── modules/      # Command handlers (dynamic discovery)
    │   └── helper/
    │       └── workflows/  # ConversationHandler flows (*_flow.py only)
    └── utils/        # Shared utilities
```

**Stack**: Python 3.12 · python-telegram-bot 22.5 · MongoDB (Motor async) · Flask  
**Entry point**: `python3 -m tcbot`  
**Tests**: `python3 -m pytest tests/ -v` — must all pass before and after any change

---

## 1. Code Style

### Imports (strict order)
```python
from __future__ import annotations   # ← ALWAYS first non-comment line

import logging                        # stdlib

from telegram import Update           # third-party
from telegram.ext import ContextTypes

from tcbot.modules.helper import decorators   # internal (tcbot.*)
from tcbot.utils.prefixes import build_prefixed_filters
```
One blank line between groups. Never wildcard imports. Never inline imports inside function bodies.

### Naming
| Construct | Convention | Example |
|---|---|---|
| Module-level private | `_snake_case` | `_render()`, `_kb()` |
| Module-level constant | `_UPPER_CASE` | `_PAGE_SIZE` |
| Class | `PascalCase` | `BanEnforcer` |
| Async handler | `cmd_*` or `on_*` | `cmd_ban_start`, `on_join_decision` |
| ConversationHandler state | `WAITING_*` | `WAITING_PROOF`, `WAITING_REASON` |

### Alignment
Align grouped assignments of 3+ variables:
```python
uid     = ban["banned_user_id"]
aid     = ban.get("admin_user_id", 0)
ban_id  = ban["ban_id"]
```

### Formatting
- Indentation: 4 spaces. No tabs.
- Max line length: 100 characters.
- Two blank lines between top-level definitions.

### Types
- `list[str]`, `dict[str, int]`, `int | None` — never `List`, `Optional`, `Union`
- `from __future__ import annotations` enables forward references everywhere

---

## 2. Comments & Section Dividers

Full reference: `agents/STYLE-COMMENTS.md`

### Better Comments — annotation prefixes
Works in both inline `#` comments and inside docstrings:

```python
# ! WARNING: dangerous behavior / # ! CRITICAL: must-not-ignore issue
# ? question or uncertainty to revisit
# TODO: deferred task (enough context to act on)
# * highlight, info, general description
# // dead code — must be removed, not disabled temporarily
```

Inside docstrings (no `#` prefix):
```python
"""
Function description.

! Must be called with mod_only permission.
? Consider adding a dry-run mode.
TODO: batch with asyncio.gather() once stable.
* Returns (banned_count, error_count).
"""
```

### Section dividers (Comment Divider extension — never hand-type)
```python
# ────────────────────────────────── H1 ───────────────────────────────── #  ← module-level
# ────────────────────────── H2 ────────────────────────── #                 ← major block
# ~~~~~~~~~~~~~~~~~~~ H3 ~~~~~~~~~~~~~~~~~~~~ #                              ← sub-block
# ~~~~~~~~~~~ H4 ~~~~~~~~~~~ #                                               ← minor grouping
```
Default to **H1** for all module-level sections.

---

## 3. Module File Structure

Every `tcbot/modules/*.py` must follow this template exactly:

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

__module_name__ = "MyModule"       # None to hide from /help
__help_text__   = "<b>Commands</b>\n..."


# ──────────────────────────── Command Name ──────────────────────────── #

@decorators.ratelimiter(limit=5, period=60)
@decorators.mod_only
@decorators.log_execution
async def cmd_example(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    ...


# ─────────────────────────────── Handlers ───────────────────────────── #

_EXAMPLE_CMDS = build_prefixed_filters("tcexample")

__handlers__ = [MessageHandler(_EXAMPLE_CMDS, cmd_example)]
```

**Module checklist (run before outputting any module file):**
- [ ] `from __future__ import annotations` as first non-comment line
- [ ] Copyright header (3 lines)
- [ ] One-line module docstring
- [ ] `__module_name__` and `__help_text__` set
- [ ] All handlers carry the 3-layer decorator stack
- [ ] `__handlers__` at the bottom
- [ ] No inline imports, no raw `col()` calls

---

## 4. Decorator Stack

Three layers, fixed order — outermost to innermost:

```python
@decorators.ratelimiter(limit=5, period=60)   # 1. outermost — rate checked first
@decorators.mod_only                          # 2. auth guard — checked second
@decorators.log_execution                     # 3. innermost — logs after auth passes
async def cmd_ban_start(...):
```

**Standard rate limits:**
| Category | limit | period |
|---|---|---|
| Destructive (ban, kick, unban, broadcast) | 3–5 | 60 |
| Moderation (mute, warn, cleanup) | 3–5 | 60 |
| Read commands (stats, groups, help) | 8 | 30 |
| Inline callbacks | 15 | 30 |
| Emergency-only (leaveall) | 1 | 300 |

Message-event handlers (`on_new_member`, etc.) are **exempt** from rate limiters.

---

## 5. Role System

**Always use canonical helpers — never chain manual checks:**

```python
from tcbot.database.roles_db import get_effective_role, can_act_on, ROLE_LABEL

role = await get_effective_role(user_id)
# → "founder" | "admin" | "developer" | "tester" | None

ok = await can_act_on(executor_id, target_id)
```

**Never** call `is_owner()` + `is_admin()` + `get_role()` manually.

**Auto-demote before ban/kick:**
```python
from tcbot.modules.helper.role_guard import auto_demote

target_role = await get_effective_role(target_id)
if target_role:
    await auto_demote(ctx.bot, target_id, target_fname, target_role,
                      executor_id, executor_fname, "ban")
# Then proceed with ban/kick
```

**Role guard for simultaneous executor + target check:**
```python
from tcbot.modules.helper.role_guard import resolve_and_check

executor_role, target_role = await resolve_and_check(
    msg, executor_id, target_id, min_role="developer"
)
if executor_role is None:
    return  # already replied with error
```

---

## 6. Database Layer

- All write operations (insert, update, delete) live in `tcbot/database/` — **never in module handlers**
- Never call `col()` directly from module code — use per-collection helper functions
- Global import pattern: `from tcbot import database as db` → `db.bans_db.get_ban(ban_id)`
- All helpers must be `async` with full type annotations
- Naming: `get_<entity>`, `get_all_<entities>`, `add_<entity>`, `update_<entity>`, `delete_<entity>`
- Index-sensitive queries must match indexes in `mongos.ensure_indexes()`
- When adding a new collection: add indexes to `ensure_indexes()` immediately
- Use `database/documents.py` for TypedDict document shapes and Literal type aliases
- Use `database/types.py` for NewType domain primitives: `UserId`, `GroupId`, `BanId`
- Use `database/cache.py` for in-memory TTL caches

---

## 7. Conversation Flows

**No `*_conv.py` files** — all ConversationHandlers live in `*_flow.py` files in `tcbot/modules/helper/workflows/`.

| Action | Use |
|---|---|
| Kick / Mute / Warn | `reason_flow.build_modaction_conv()` — never duplicate state handlers |
| Ban | `ban_flow.ban_conversation(entry_fn)` — album-aware proof flow |
| Appeal | `appeal_flow.build_handler()` — standalone deep-link flow |
| New flow | Model after `appeal_flow.py` |

States are always `WAITING_*` module-level constants. Every flow must have a `cancel` fallback. Timeouts must use `cfg.proof_timeout` or `cfg.appeal_timeout` — never hardcoded integers.

---

## 8. HTML Formatting

Always `parse_mode="HTML"`. Never Markdown. Canonical helpers from `tcbot/modules/helper/formatter.py`:

```python
from tcbot.modules.helper.formatter import esc, code, mention, bold

esc(user_input)        # escape &, <, > — ALWAYS on user-provided strings
code("123456789")      # <code>123456789</code>
mention(uid, fname)    # <a href="tg://user?id=uid">fname</a>
bold("text")           # <b>text</b>
```

Multi-line strings use parenthesized concatenation:
```python
text = (
    "<b>Ban Information</b>\n\n"
    f"User: {mention(uid, fname)}\n"
    f"Ban ID: {code(ban_id)}"
)
```

Do not use `mention(x) + code(x)` — pick one per context.

---

## 9. Async Patterns

```python
# Good — parallel
executor_role, (target_id, fname) = await asyncio.gather(
    get_effective_role(admin.id),
    extraction.extract_target(update, args, ctx.bot),
)
```

Fan-out to multiple groups must go through `fan_out()`:
```python
from tcbot.utils.dispatch import fan_out

groups  = await db.groups_db.active_groups()
results = await fan_out([
    ctx.bot.ban_chat_member(g["chat_id"], target_id)
    for g in groups
])
errors = sum(1 for r in results if isinstance(r, BaseException))
```

`fan_out()` caps concurrency at 10, never raises, returns results in order.

---

## 10. Telegram API Rules

- Always `await q.answer()` before any further action in a `CallbackQueryHandler`
- Wrap every `bot.send_message` / `bot.ban_chat_member` in try/except when iterating over groups
- Never store `Update` or `Message` objects beyond the handler call lifetime
- Never use `q._bot` — use `ctx.bot`

---

## 11. Bot Persona Pattern

Required for every command that targets a user:

```python
# 1. Bot self-check
if target_id == ctx.bot.id:
    await msg.reply_text("That's me — [context]. 😄", parse_mode="HTML")
    return

# 2. Role check
target_role = await get_effective_role(target_id)
if target_role == "founder":
    fname = await db.users_db.get_first_name(target_id, "the Founder")
    await msg.reply_text(
        f"That's {mention(target_id, fname)}, our Founder — [context]. 👑",
        parse_mode="HTML",
    )
    return
if target_role in ("admin", "developer", "tester"):
    label = ROLE_LABEL.get(target_role, target_role.capitalize())
    fname = await db.users_db.get_first_name(target_id, str(target_id))
    await msg.reply_text(
        f"That's a {cfg.community_name} {label} — [context].",
        parse_mode="HTML",
    )
    return
```

Tone: friendly-formal. 1–3 emojis per message. Short and direct. No filler phrases.

---

## 12. Datetime

Never use `datetime.utcnow()` or `datetime.now(timezone.utc)` anywhere. Always import from `tcbot.utils.timedate_format`:

| Function | Use when |
|---|---|
| `utc_now()` | Storing timestamps in DB, elapsed-time checks |
| `to_utc(dt)` | Normalizing before subtracting datetimes |
| `fmt_dt(dt)` | Displaying any datetime to users |
| `utc_now_str()` | One-line formatted current time |

---

## 13. Secret & Credential Safety

Before outputting any code, scan for:

| Pattern | Action |
|---|---|
| Bot tokens (`\d+:[A-Za-z0-9_-]{35,}`) | BLOCK — replace with `os.getenv("BOT_TOKEN")` |
| MongoDB URIs (`mongodb://`, `mongodb+srv://`) | BLOCK — replace with `os.getenv("MONGO_URI")` |
| Any API key, webhook secret, password | BLOCK — replace with env var reference |

If detected: show `⚠️ SECRET DETECTED — replaced with environment variable reference.`  
On Replit: secrets go in Replit Secrets panel. `config.env` is for non-sensitive config only and is gitignored.

---

## 14. File Creation Policy

Before creating any new file:
- Can this logic fit in an **existing module** that owns this feature area?
- Can this be a helper function added to an existing file in `tcbot/modules/helper/`?

**Allowed:** New `tcbot/modules/<name>.py` for a genuinely new command group.  
**Allowed:** New `tcbot/modules/helper/workflows/<name>_flow.py` for a new conversation flow.  
**Allowed:** New `tcbot/database/<name>_db.py` for a new MongoDB collection.  
**Forbidden:** `*_conv.py` files — flows belong in `*_flow.py`.  
**Forbidden:** Keyboard functions anywhere except `tcbot/modules/helper/keyboards.py`.  
**Forbidden:** Duplicating logic that already exists in another module — refactor instead.  
**Forbidden:** Adding packages to `requirements.txt` — use `uv add <package>` → `pyproject.toml`.

---

## 15. Testing

- All 134 tests run offline — no bot token or MongoDB connection required
- Run `python3 -m pytest tests/ -v` before **and** after every change
- New DB functions → test in `tests/test_<entity>_db.py`
- New decorators/helpers → test alongside existing `tests/test_decorators.py` etc.
- Use `tests/conftest.py` for shared fixtures — do not duplicate setup
- Tests must be pure — mock external dependencies (DB, Telegram API)

---

## 16. General Rules

- **No dead code** — unused functions, imports, and variables must be removed
- **No duplicate logic** — if a pattern appears in two modules, extract to a shared helper
- **No silent fallbacks** — always log at minimum `log.debug()`, never bare `except: pass`
- **No `print()`** — use `log = logging.getLogger(__name__)` only
- **Backward compatibility** — every change must be backward-compatible with existing MongoDB data. Never rename/delete collection fields without a migration plan
- **Minimal diff** — when editing, change only what's necessary. Don't reformat unrelated lines
- **All bot responses in English** with `parse_mode="HTML"`

---

## Final Checklist — Before Outputting Any Code

- [ ] `from __future__ import annotations` present as first non-comment line?
- [ ] Copyright header (3 lines)?
- [ ] Imports in correct order and grouped?
- [ ] All non-obvious functions have single-line docstrings?
- [ ] Better Comments prefixes used correctly (`# !`, `# ?`, `# TODO:`, `# *`, `# //`)?
- [ ] Section dividers are H1/H2/H3/H4 format (not hand-typed)?
- [ ] `snake_case` naming, `WAITING_*` for states, `cmd_*`/`on_*` for handlers?
- [ ] 3-layer decorator stack in correct order?
- [ ] No secrets or hardcoded credentials?
- [ ] DB access only through `tcbot/database/` layer?
- [ ] No `*_conv.py` files — flows in `*_flow.py` only?
- [ ] `asyncio.gather()` used for parallel async ops?
- [ ] Fan-out operations use `fan_out()` from `dispatch.py`?
- [ ] `auto_demote()` called before ban/kick when target holds a role?
- [ ] `await q.answer()` before any callback action?
- [ ] All datetimes via `tcbot.utils.timedate_format`?
- [ ] No `print()` — using `log` only?
- [ ] No unnecessary new files created?
- [ ] Tests still pass after the change?