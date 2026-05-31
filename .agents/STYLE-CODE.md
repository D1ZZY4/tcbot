# Code Style — TCF Bot

Read [`CLAUDE.md`](CLAUDE.md) first. This file defines Python code style for TCF Bot. Use it together with [`RULES.md`](RULES.md) and [`STYLE-COMMENTS.md`](STYLE-COMMENTS.md). For development workflow, see [`WORKFLOW.md`](WORKFLOW.md). For testing and Ruff commands, see [`TEST-RUFF.md`](TEST-RUFF.md).

---

## Language and Tooling

- Python 3.12.
- Ruff formatter and linter.
- Ruff configuration lives in `pyproject.toml`.
- Use `uv` for dependency and tool execution.

Commands:

```bash
uv run ruff format .
uv run ruff check --fix .
uv run --extra test pytest tests/ -v
```

---

## File Header

Every Python module starts with this structure:

```python
# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""One-line description of what this module does."""

from __future__ import annotations
```

Rules:

- The module docstring is a single sentence ending with a period.
- `from __future__ import annotations` is the first non-comment code line.
- Do not put imports, constants, or executable code before the future import.

---

## Imports

Import order:

1. Future import.
2. Standard library.
3. Third-party packages such as `telegram`, `telegram.ext`, `motor`, `flask`.
4. Internal `tcbot.*` imports.

Example:

```python
from __future__ import annotations

import asyncio
import logging

from telegram import Update
from telegram.ext import ContextTypes, MessageHandler

from tcbot import cfg
from tcbot import database as db
from tcbot.modules.helper import decorators, extraction
from tcbot.utils.prefixes import build_prefixed_filters
```

Rules:

- One blank line between import groups.
- No wildcard imports.
- No inline imports inside functions.
- Prefer `from tcbot import database as db` for database access in modules.
- Prefer `from tcbot import cfg` for configuration in modules.
- Do not import raw environment variables outside `tcbot/__init__.py`.

---

## Typing

Use modern Python 3.12 type syntax:

```python
users: list[int] = []
counts: dict[str, int] = {}
pair: tuple[int, int | None]
name: str | None = None
```

Rules:

- Prefer `list`, `dict`, `set`, `tuple` over `typing.List`, `typing.Dict`, etc.
- Prefer `X | None` over `Optional[X]`.
- Use `collections.abc` for callable/iterable abstractions when needed.
- Use `TypedDict` document shapes from `tcbot/database/documents.py`.
- Use `NewType` primitives from `tcbot/database/types.py` for domain IDs when a
  DB API already uses them.
- Public functions and methods require explicit parameter and return types.

---

## Naming

| Construct | Convention | Example |
|---|---|---|
| Module-level private helper | `_snake_case` | `_render_ban()` |
| Module-level constant | `_UPPER_CASE` | `_PAGE_SIZE` |
| Public function | `snake_case` | `get_effective_role()` |
| Class | `PascalCase` | `BuildProof` |
| Dataclass result | `PascalCase` | `SweepResult` |
| Async command handler | `cmd_*` | `cmd_ban_start` |
| Async event/callback handler | `on_*` | `on_join_decision` |
| Conversation state | `WAITING_*` | `WAITING_PROOF` |
| Command filter constant | `_NAME_CMDS` | `_BAN_CMDS` |

---

## Formatting and Layout

- Use 4 spaces for indentation.
- No tabs.
- Keep code compatible with Ruff formatting.
- Use two blank lines between top-level functions/classes after formatting.
- Keep functions focused and small enough to read without excessive scrolling.
- Prefer early returns over deeply nested conditionals.

Align related assignment groups only when it improves readability and there are
three or more adjacent values:

```python
uid    = ban["banned_user_id"]
aid    = ban.get("admin_user_id", 0)
ban_id = ban["ban_id"]
```

Do not force alignment for isolated assignments.

---

## Strings and HTML Messages

Use f-strings for interpolation:

```python
text = f"Ban ID: {code(ban_id)}"
```

Use parenthesized concatenation for multi-line messages:

```python
text = (
    "<b>Ban Information</b>\n\n"
    f"User: {mention(uid, fname)}\n"
    f"Ban ID: {code(ban_id)}"
)
```

Rules:

- User-facing Telegram messages always use `parse_mode="HTML"`.
- Never use Markdown parse mode.
- Escape user-provided strings with `esc()`.
- Use `mention()` for clickable user names.
- Use `code()` for IDs and identifiers.
- Use `bold()` for static bold labels.
- Do not combine `mention(x)` and `code(x)` for the same value.
- Keep tone friendly-formal, concise, and English-only.

---

## Logging and Errors

```python
log = logging.getLogger(__name__)
```

Rules:

- Use module loggers, not `print()`.
- Use `try/except Exception` at I/O boundaries such as Telegram API calls and DB
  writes.
- Log failures with actionable context.
- Do not swallow exceptions silently.
- In handlers, reply gracefully to the user when the action cannot continue.
- In multi-group operations, one failed group must not abort the whole fan-out.

---

## Decorator Stack

Command and callback handlers use this order:

```python
@decorators.ratelimiter(limit=5, period=60)
@decorators.mod_only
@decorators.log_execution
async def cmd_example(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    ...
```

When no auth guard applies:

```python
@decorators.ratelimiter(limit=8, period=30)
@decorators.log_execution
async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    ...
```

Message-event handlers are exempt from per-handler rate-limit decorators.

---

## Command Module Structure

Use this template for `tcbot/modules/*.py` files:

```python
# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""One-line description of this command module."""

from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes, MessageHandler

from tcbot.modules.helper import decorators
from tcbot.utils.prefixes import build_prefixed_filters

log = logging.getLogger(__name__)

__module_name__ = "Example"
__help_text__   = "<b>Commands</b>\n/tcexample - Explain the command."


# ─────────────────────────────── Commands ───────────────────────────── #

@decorators.ratelimiter(limit=5, period=60)
@decorators.mod_only
@decorators.log_execution
async def cmd_example(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    ...


# ─────────────────────────────── Handlers ───────────────────────────── #

_EXAMPLE_CMDS = build_prefixed_filters("tcexample")

__handlers__ = [MessageHandler(_EXAMPLE_CMDS, cmd_example)]
```

---

## Database Access Style

In command modules:

```python
from tcbot import database as db

ban = await db.bans_db.get_ban(ban_id)
```

Rules:

- No raw `col()` calls outside database helper modules.
- No direct insert/update/delete in command modules.
- Use `*_db.py` helpers for collection access.
- Add indexes in `mongos.ensure_indexes()` for new indexed queries.
- Keep DB helpers async and typed.

---

## Role and Target Handling

Use shared helpers:

```python
from tcbot import database as db
from tcbot.modules.helper import extraction
from tcbot.modules.helper.decorators import resolve_and_check

# Extract target from command
target_id, target_fname = await extraction.extract_target(update, args, ctx.bot)

# Check roles and permissions (uses db.users_roles internally)
executor_role, target_role = await resolve_and_check(
    msg, executor_id, target_id, min_role="developer"
)

# Or check roles manually
role = await db.users_roles.get_effective_role(user_id)
label = db.users_roles.ROLE_LABEL.get(role, role)
```

Rules:

- Do not reimplement target parsing.
- Do not manually chain owner/admin/role checks.
- Do not compare role ranks inline in command modules.
- Always protect the bot itself and privileged roles before targeted actions.

---

## Conversation Flow Style

- Flow files live in `tcbot/modules/helper/workflows/`.
- Flow files are named `*_flow.py`.
- State constants are `WAITING_*`.
- Kick, mute, and warn use `reason_flow.build_modaction_conv()`.
- Ban uses `ban_flow.ban_conversation()`.
- Appeal uses `appeal_flow.build_handler()`.
- New standalone flows should follow `appeal_flow.py`.

---

## Datetime Style

Use only helpers from `tcbot.utils.timedate_format`:

```python
from tcbot.utils.timedate_format import fmt_dt, to_utc, utc_now
```

Do not use `datetime.utcnow()` or inline `datetime.now(timezone.utc)` outside the
helper module.

---

## What Not To Do

- Do not inline imports.
- Do not add `typing.List`, `typing.Optional`, or `typing.Union` in new code.
- Do not use Markdown parse mode.
- Do not define keyboards outside `keyboards.py`.
- Do not create `*_conv.py` files.
- Do not duplicate reason/proof workflow code.
- Do not use `q._bot` or other PTB private attributes.
- Do not hardcode secrets, chat IDs for deployments, or tokens.
- Do not add dependencies to `requirements.txt`.
