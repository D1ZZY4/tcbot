# AI Agent Instructions — TCF Bot

Read this file completely before making any change to this repository. It is the
canonical project reference for AI coding agents. The other files in `agents/`
expand specific topics and must stay consistent with this file.

Compatible with: Claude, Replit AI, Gemini, Qwen, GitHub Copilot, and any AI
coding agent.

---

## Project Identity

TCF Bot is a production Telegram federation management bot for the Transsion Core
Federation community. It manages federation-wide bans, appeals, staff roles,
connected groups, per-group moderation, and audit logging.

| Area | Current standard |
|---|---|
| Language | Python 3.12 |
| Bot framework | `python-telegram-bot` 22.5, async, long polling |
| Database | MongoDB through Motor async |
| Keep-alive | Flask health endpoint, default local port 5000 |
| Replit port | `PORT=8080` |
| Entry point | `python3 -m tcbot` |
| Dependencies | `uv`, `pyproject.toml`, `uv.lock` |
| Formatter/linter | Ruff (`uv run ruff format .`, `uv run ruff check --fix .`) |
| Tests | `python3 -m pytest tests/ -v`, offline tests |

Secrets are never committed. On Replit, put `BOT_TOKEN` and `MONGODB_URI` in
Replit Secrets. For local development, use a gitignored `config.env` copied from
`config.env.example`.

---

## Repository Map

```text
tgbot/
├── agents/                         AI-agent policy and workflow docs
├── docs/                           Human-facing architecture and module docs
├── tests/                          Offline pytest suite
├── tcbot/
│   ├── __init__.py                 Configs dataclass + global cfg adapter
│   ├── __main__.py                 Startup, handlers, polling, error handling
│   ├── alive.py                    Flask keep-alive server
│   ├── database/                   Async MongoDB helpers, one file per area
│   │   ├── users_db.py             Member cache + owners + admins + developer/tester roles, effective-role resolution
│   │   ├── bans_db.py              Federation bans
│   │   ├── cache.py                In-memory TTL caches
│   │   ├── documents.py            TypedDict document shapes and Literal aliases
│   │   ├── groups_db.py            Connected groups and join queue
│   │   ├── kicks_db.py             Kick log
│   │   ├── mongos.py               Motor client, connect(), indexes, col()
│   │   ├── mutes_db.py             Mute log
│   │   ├── queues_db.py            Promotion request queue
│   │   ├── types.py                NewType domain primitives
│   │   ├── warns_db.py             Warning records and counts
│   │   └── mongos.py               Motor client, connect(), indexes, col()
│   ├── modules/                    Telegram command modules
│   │   ├── helper/                 Shared decorators, formatting, keyboards
│   │   │   └── workflows/          ConversationHandler flows (`*_flow.py` only)
│   │   └── *.py                    Dynamic modules exposing `__handlers__`
│   └── utils/                      Dispatch, logging, prefixes, datetime helpers
├── config.env.example              Environment template; no real secrets
├── pyproject.toml                  Python metadata, Ruff, pytest config
└── uv.lock                         Locked dependencies
```

---

## Before Making Changes

1. Confirm the requested files are in scope. Do not edit unrelated files.
2. Read the full file you plan to edit and inspect nearby patterns.
3. Search for existing helpers before adding new logic.
4. Preserve backward compatibility with existing MongoDB data.
5. Never expose, move, or hardcode secrets.
6. For code changes, run the most relevant tests before and after when possible.

For documentation-only work, do not edit code to make docs match old behavior.
Instead, document the current canonical policy and note validation limitations.

---

## Global Imports and Configuration

Use this pattern in module code:

```python
from tcbot import cfg
from tcbot import database as db
```

Rules:

- Use `cfg`, not the raw `configs` dataclass, in feature modules.
- Use `from tcbot import database as db` for database namespace access.
- Do not import `config.env` values directly outside the config layer.
- Never inline-import inside functions.

---

## Code Style Summary

Full details: `agents/STYLE-CODE.md` and `agents/STYLE-COMMENTS.md`.

Required Python module header:

```python
# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""One-line description of what this module does."""

from __future__ import annotations
```

Import order:

1. `from __future__ import annotations`
2. Standard library
3. Third-party packages
4. Internal `tcbot.*` imports

Other rules:

- Python 3.12 syntax only.
- Prefer built-in generics: `list[str]`, `dict[str, int]`, `tuple[int, ...]`.
- Prefer `X | None` over `Optional[X]`.
- Ruff is configured in `pyproject.toml`; keep code compatible with Ruff format.
- Use 4-space indentation, no tabs.
- Use f-strings for interpolation.
- Use `log = logging.getLogger(__name__)`, never `print()` in application code.

---

## Module File Pattern

Every `tcbot/modules/*.py` file must expose help metadata and handlers:

```python
# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""One-line description of the command module."""

from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes, MessageHandler

from tcbot.modules.helper import decorators
from tcbot.utils.prefixes import build_prefixed_filters

log = logging.getLogger(__name__)

__module_name__ = "Module Name"       # Use None to hide from /help.
__help_text__   = "<b>Commands</b>\n..."


# ─────────────────────────────── Example ───────────────────────────── #

@decorators.ratelimiter(limit=5, period=60)
@decorators.mod_only
@decorators.log_execution
async def cmd_example(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    ...


# ─────────────────────────────── Handlers ───────────────────────────── #

_EXAMPLE_CMDS = build_prefixed_filters("tcexample")

__handlers__ = [MessageHandler(_EXAMPLE_CMDS, cmd_example)]
```

Checklist:

- `from __future__ import annotations` is the first non-comment line.
- Copyright header is present.
- One-line module docstring is present.
- `__module_name__` and `__help_text__` are correct.
- Command/callback handlers use the required decorator stack.
- Filters use helpers from `tcbot.utils.prefixes`.
- `__handlers__` is at the bottom.
- No inline imports, no raw DB writes, no local keyboard builders.

---

## Decorator Stack

Every command handler and callback handler uses the fixed stack, outermost to
innermost:

```python
@decorators.ratelimiter(limit=5, period=60)
@decorators.mod_only
@decorators.log_execution
async def cmd_ban_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    ...
```

When no auth guard is needed:

```python
@decorators.ratelimiter(limit=8, period=30)
@decorators.log_execution
async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    ...
```

Standard auth guards:

| Guard | Allowed roles | Typical use |
|---|---|---|
| `owner_only` | Founder | ownership transfer, dangerous maintenance |
| `staff_only` | Founder, Admin | staff-only management views |
| `mod_only` | Founder, Admin, Developer | ban, unban, federation actions |
| `basic_mod_only` | Founder, Admin, Developer, Tester | kick, mute, warn |

Standard rate limits:

| Category | Limit | Period |
|---|---:|---:|
| Destructive commands: ban, kick, unban, broadcast | 3–5 | 60s |
| Moderation commands: mute, warn, cleanup | 3–5 | 60s |
| Read commands: stats, groups, checkme, help | 8 | 30s |
| Inline callbacks | 15 | 30s |
| Emergency-only actions | 1 | 300s |

Message-event handlers such as `on_new_member` are exempt from per-handler
rate-limit decorators.

---

## Role System

Hierarchy:

| Role | Rank | Collection | Notes |
|---|---:|---|---|
| Founder | 4 | `tc_owners` | Full access and ownership transfer |
| Admin | 3 | `tc_admins` | Staff management and moderation |
| Developer | 2 | `tc_roles` | Federation ban/unban and lower actions |
| Tester | 1 | `tc_roles` | Kick, mute, warn |

Canonical helpers:

```python
from tcbot.database.users_db import ROLE_LABEL, can_act_on, get_effective_role

role = await get_effective_role(user_id)
# "founder" | "admin" | "developer" | "tester" | None

ok = await can_act_on(executor_id, target_id)
```

Rules:

- Do not manually chain `is_owner()` + `is_admin()` + `get_role()` in modules.
- Do not compare role ranks inline; use `can_act_on()` or `resolve_and_check()`.
- Use `ROLE_LABEL` for user-facing role names.
- Developer and Tester roles are stored in `tc_roles`.
- Admin promotion requests use `queues_db`; do not bypass the queue unless the
  existing workflow explicitly allows a Founder action.

For commands that target a user, use the shared guard from `decorators`:

```python
from tcbot.modules.helper.decorators import resolve_and_check

executor_role, target_role = await resolve_and_check(
    msg, executor_id, target_id, min_role="developer"
)
if executor_role is None:
    return
```

Auto-demote before ban or kick uses the `Demote` class:

```python
from tcbot.modules.helper.workflows.demote_flow import Demote

target_role = await get_effective_role(target_id)
if target_role:
    await Demote.execute(
        ctx.bot,
        target_id,
        target_fname,
        target_role,
        executor_id,
        executor_fname,
        trigger="ban",  # or "kick"
    )
```

---

## Database Rules

- All MongoDB write operations live in `tcbot/database/` helper modules.
- Module handlers never call `col()` directly and never write collections inline.
- Keep one DB concern per `*_db.py` file.
- DB helper names should be explicit: `get_*`, `get_all_*`, `add_*`, `update_*`,
  `delete_*`, `deactivate_*`, etc.
- All DB helpers are async and fully typed.
- New collections require indexes in `tcbot/database/mongos.py::ensure_indexes()`.
- Index-sensitive queries must match existing indexes.
- Use `tcbot/database/documents.py` for document `TypedDict` shapes.
- Use `tcbot/database/types.py` for domain `NewType` primitives.
- Use `tcbot/database/cache.py` for in-memory TTL caches and invalidate caches on
  writes.
- Never rename or remove stored fields without a migration plan and read-path
  compatibility.

---

## Conversation Flows

All `ConversationHandler` flows live under
`tcbot/modules/helper/workflows/` and use `*_flow.py` filenames. Never create
`*_conv.py` files.

| Action | Canonical pattern |
|---|---|
| Kick / Mute / Warn | `reason_flow.build_modaction_conv()` |
| Ban | `ban_flow.ban_conversation(entry_fn)` |
| Appeal | `appeal_flow.build_handler()` |
| New standalone flow | Model after `appeal_flow.py` |

Rules:

- State constants are module-level `WAITING_*` names.
- Every conversation flow has a cancel fallback.
- Proof and appeal timeouts use `cfg.proof_timeout` and `cfg.appeal_timeout`.
- Do not duplicate reason/proof state handlers.
- Module files define command filters and pass entry functions into flow factories.

---

## Formatting Telegram Messages

All user-facing bot messages use `parse_mode="HTML"`. Never use Markdown.

Canonical helpers from `tcbot/modules/helper/formatter.py`:

```python
from tcbot.modules.helper.formatter import bold, code, esc, mention

esc(user_input)        # Escape user-provided strings.
code("123456789")      # Format IDs and identifiers.
mention(uid, fname)    # Clickable user mention.
bold("text")           # Bold static text.
```

Rules:

- Escape every user-provided string with `esc()` unless another helper already
  escapes it.
- Use `mention()` for user display and `code()` for IDs; do not concatenate both
  for the same value.
- Use parenthesized multi-line strings, not backslash continuation.
- Tone is friendly-formal, short, and direct; use 1–3 emojis only where natural.
- All bot responses must be in English.

---

## Target Resolution

Use `extract_target()` for command target parsing:

```python
from tcbot.modules.helper import extraction

target_id, target_fname = await extraction.extract_target(update, args, ctx.bot)
if target_id is None:
    return
```

Resolution order:

1. Explicit argument as numeric ID or username.
2. Reply target when no explicit argument is provided.
3. `text_mention` entity.
4. `@mention` entity resolved through Telegram.

Do not reimplement target parsing inside command modules.

---

## Datetime Rules

Never call `datetime.utcnow()` or inline `datetime.now(timezone.utc)` outside the
datetime utility module. Import helpers from `tcbot.utils.timedate_format`.

| Helper | Use |
|---|---|
| `utc_now()` | Store timestamps and compare elapsed time |
| `to_utc(dt)` | Normalize DB datetimes before arithmetic |
| `fmt_dt(dt)` | Show datetimes to users |
| `utc_now_str()` | Show the current UTC time as text |

---

## Async and Telegram API Rules

- Use `asyncio.gather()` for independent async operations.
- Use `tcbot.utils.dispatch.fan_out()` for multi-group operations; it limits
  concurrency and returns exceptions as results.
- Always `await q.answer()` before doing any other callback-query work.
- Wrap repeated Telegram API calls in `try/except` so one group failure does not
  abort the whole operation.
- Do not store `Update`, `Message`, or `CallbackQuery` objects beyond the handler
  call lifetime.
- Do not use PTB private attributes such as `q._bot`; use `ctx.bot`.

---

## Bot Persona for Targeted Actions

Every command that targets a user must guard special targets before acting:

1. Bot self-check: never ban, kick, mute, warn, or demote the bot itself.
2. Founder check: respond respectfully and stop.
3. Staff role check: use `get_effective_role()`, `ROLE_LABEL`, and
- Role checks should use the canonical role helpers in `tcbot.database.users_db` and the shared guard in `tcbot.modules.helper.decorators.resolve_and_check`.
4. Auto-demote staff targets before ban or kick when allowed.

Keep responses clear, English-only, HTML formatted, and short.

---

## Testing and Quality Commands

Install dependencies:

```bash
uv sync
```

Run tests:

```bash
python3 -m pytest tests/ -v
```

Format and lint:

```bash
uv run ruff format .
uv run ruff check --fix .
```

If `python3` is unavailable on Windows, use the project interpreter or `uv run`
when available. Do not claim tests passed unless you ran them successfully.

---

## Security Rules

- Never commit `config.env` or real credentials.
- Never paste bot tokens, MongoDB URIs, passwords, API keys, or webhook secrets
  into docs, code, tests, logs, or comments.
- Use environment variables for all secrets.
- On Replit, store production secrets in Replit Secrets.
- `config.env.example` may contain placeholder values only.
- Treat logs and screenshots as sensitive if they include user IDs, invite links,
  tokens, database names, or message links.

---

## What Not To Do

- Do not edit files outside the requested scope.
- Do not add packages to `requirements.txt`; use `uv add <package>` when a new
  dependency is justified.
- Do not create `*_conv.py` files.
- Do not add keyboard builders outside `tcbot/modules/helper/keyboards.py`.
- Do not duplicate existing workflow, role, formatter, or DB logic.
- Do not silently swallow exceptions.
- Do not use Markdown parse mode for bot messages.
- Do not store Telegram objects outside handler scope.
- Do not make schema-breaking MongoDB changes without a migration plan.

---

## Bot Voice

The bot speaks to users in **professional + friendly + lightly humorous** English. Replies are short, plain-text, and human; no exclamation cascades, no marketing tone.

- **Pictograph emoji are forbidden** (waving hands, party poppers, prohibition signs, warning signs, coloured squares, and the like). Strip them on sight.
- **Text emoticons are allowed sparingly** when they fit a joke beat: `:)`, `:v`, `:')`, `:D`. At most one per reply, and only in the *witty refusal* path — never in success/error/data views.
- The bot identifies the target before speaking. The canonical identity classes are defined in `tcbot/modules/helper/identity.py`:
  - `self` — the executor targeted themselves
  - `this_bot` — this bot is the target
  - `other_bot` — any other Telegram bot
  - `telegram` — Telegram service account (id `777000`)
  - `founder`, `admin`, `developer`, `tester` — federation roles
  - `user` — regular user, no federation role
- Use `identity.classify(...)` plus `identity.refuse_message(action, ident)` and `identity.staff_notice(action, ident, community)` instead of repeating self/bot/founder branches inline. Each moderation entry handler should follow this shape:

```python
ident, (executor_role, target_role) = await asyncio.gather(
    identity.classify(ctx.bot, admin.id, target_id, target_fname),
    resolve_and_check(msg, admin.id, target_id, min_role="..."),
)
refusal = identity.refuse_message("ban", ident)
if refusal is not None:
    await msg.reply_text(refusal, parse_mode="HTML")
    return ConversationHandler.END
```

- Refusal copy belongs in `identity.py`, not in `modules/*.py`. Add new lines or new actions there so the voice stays consistent across the whole bot.

---

## Async + Parallelism Rules

This bot must respond with **zero perceived delay**. The hot path of every command handler should issue independent async work in parallel.

- Any two `await`s that do not depend on each other **must** be combined with `asyncio.gather(...)`. Sequential awaits are a defect.
- Cache-only reads (`users_db.get_first_name`, `get_effective_role`) are still awaits — gather them with the DB writes / Telegram calls that happen alongside.
- For lists rendered in a loop (kicks, mutes, warns, bans), resolve every per-item lookup *before* the formatting loop runs. The loop itself stays synchronous string-building.
- External Telegram lookups (`bot.get_chat`) **must** be wrapped in `asyncio.wait_for(timeout=3.0)` so a stalled API call cannot block a user-facing reply.
- DM + log + audit writes that fan out to multiple chats use `asyncio.gather(..., return_exceptions=True)` — one recipient failing must not roll back the others.
- Module-level handler registration is the only place sequential awaits are acceptable.

If you add a new handler, prove the parallelism in code review by pointing at the `asyncio.gather` block. If there isn't one, justify why every read/write in that handler is dependent on the previous.

---

## Always Update Docs After Refactors

Whenever you rename, move, or replace an internal API, **update every reference in the same change**. Do not wait to be told. The repository keeps the following sources in sync at all times:

| Surface | What to update |
|---|---|
| `docs/*.md` | Detailed feature docs (e.g. `check-detailed.md`, `promote-detailed.md`, `demote-detailed.md`, `banning-detailed.md`, `appeal-detailed.md`, `warnings-detailed.md`, `role-detailed.md`) |
| `docs/{databases,helper,modules,utils,workflows}/*.md` | Per-package reference docs |
| `docs/mapping.md` | The repository tree at the top of the docs |
| `docs/README.md` | The "Detailed feature guides" index |
| `agents/*.md` | All agent policy files (especially `agents/CLAUDE.md` repo map + `RULES.md`) |
| `agents/skills/*/SKILL.md` | Reusable agent skills referencing canonical helpers |
| `agents/agents/*.md` | Project-local sub-agent prompts (coordinator, debug-investigator, etc.) |
| `PLAN.md`, `AGENTS.md` | Top-level planning + AI agent entry points |

Steps every refactor must perform:

1. Rename / move / replace the API.
2. Run `uv run ruff check --fix . && uv run ruff format . && uv run --extra test pytest tests/ -q` and fix anything that breaks.
3. Grep the entire repo for the **old** name (and any obvious aliases) — every match is a doc to update or delete:
   ```bash
   grep -RIn 'old_name\|old.module\|old/path' agents docs PLAN.md AGENTS.md README.md .agents
   ```
4. When you add a new feature, write its `docs/<feature>-detailed.md` in the same change and add a row to `docs/README.md`.
5. When you delete an API, remove every doc reference to it. Do not leave "see also" stubs pointing at vanished symbols.
6. Restart the bot and confirm clean startup before declaring done.

Skipping the doc sweep is a defect of the same severity as a failing test.

---



| File | Purpose |
|---|---|
| `agents/RULES.md` | Hard constraints and forbidden actions |
| `agents/STYLE-CODE.md` | Python style, imports, typing, handlers |
| `agents/STYLE-COMMENTS.md` | Comments, docstrings, section dividers |
| `agents/TEST-RUFF.md` | Test, Ruff, and validation workflow |
| `agents/WORKFLOW.md` | Development process, commits, deployment checks |
| `agents/REPLIT.md` | Replit-specific run, secrets, and port guidance |
