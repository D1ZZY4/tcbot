# Code Style — TCF Bot

**Read `agents/CLAUDE.md` first.** This file defines all code formatting decisions for the project.

Compatible with: Replit AI, Claude, Gemini, Qwen, GitHub Copilot, and any AI coding agent.

---

## Language and Runtime

- Python 3.13
- Built-in generic types: `list[str]`, `dict[str, int]`, `tuple[int, int | None]`
- Union syntax: `X | Y` — never `Optional[X]` or `Union[X, Y]`
- Always add `from __future__ import annotations` as the first non-comment line in every module file

---

## Imports

Order (enforced by convention):

1. `from __future__ import annotations`
2. Standard library
3. Third-party (`telegram`, `motor`, `flask`, etc.)
4. Internal (`tcbot.*`)

One blank line between each group. Never inline imports inside function bodies.

---

## Naming

| Construct | Convention | Example |
|---|---|---|
| Module-level private | `_snake_case` | `_render()`, `_kb()` |
| Module-level constant | `_UPPER_CASE` | `_PAGE_SIZE`, `_HELP_INDEX_TEXT` |
| Class | `PascalCase` | `BanEnforcer`, `SweepResult` |
| Async handler | `cmd_*` or `on_*` | `cmd_ban_start`, `on_join_decision` |
| ConversationHandler state | `WAITING_*` | `WAITING_PROOF`, `WAITING_REASON` |

---

## Alignment

Align related assignment groups for readability when there are 3 or more adjacent assignments of the same logical type:

```python
# Good
uid     = ban["banned_user_id"]
aid     = ban.get("admin_user_id", 0)
ban_id  = ban["ban_id"]

# Not preferred for grouped blocks
uid = ban["banned_user_id"]
aid = ban.get("admin_user_id", 0)
ban_id = ban["ban_id"]
```

This applies to multi-line variable blocks, not single assignments.

---

## Section Dividers

Separate logical sections with the following format. The title line must be exactly **70 characters** wide with the text centered and flanked by `#` and `─` characters:

```python
# ────────────────────────── Section Title ───────────────────────── #
```

Comment annotation prefixes:

```python
# ! WARNING: Short or long warning description
# ! CRITICAL: Short or long critical description
# TODO: Short or long deferred task
# NOTE: Short or long note
# ? Short or long question
# * Short or long highlight, info, or general description
```

Use section dividers for major logical blocks within a file — not for every minor group of lines.

Do not add comments that explain what the next line obviously does:

```python
# Bad
# * Get the user ID
uid = update.effective_user.id

# Good — no comment needed
uid = update.effective_user.id
```

---

## String Formatting

- Use f-strings for all string interpolation
- HTML responses use `esc()` for user-provided text, `mention()` for clickable names, `code()` for IDs and identifiers
- Multi-line strings use parenthesized concatenation, not backslash continuation:

```python
text = (
    "<b>Ban Information</b>\n\n"
    f"User: {mention(uid, fname)}\n"
    f"Ban ID: {code(ban_id)}"
)
```

---

## Error Handling

- Use `try/except Exception` only at I/O boundaries (Telegram API calls, DB writes)
- Always log errors: `log.error("Context: %s", exc)` or `log.warning(...)`
- Do not raise exceptions inside handlers — handle gracefully and reply to the user
- Never use bare `except: pass` — always log at minimum `log.debug()`

---

## Dataclasses

Use `@dataclass` for result containers. Use `frozen=True` for config and immutable objects:

```python
@dataclass
class SweepResult:
    chat_id: int
    banned:  int = 0
    errors:  int = 0

@dataclass(frozen=True)
class Configs:
    bot_token: str
    owner_id:  int
```

---

## Decorator Stack

Three layers in fixed order — **outermost to innermost**:

1. `@decorators.ratelimiter(limit, period)` — outermost; throttles per-user call rate
2. `@decorators.owner_only` / `staff_only` / `mod_only` / `basic_mod_only` — auth guard
3. `@decorators.log_execution` — innermost; logs entry, exit, and elapsed ms after auth passes

```python
@decorators.ratelimiter(limit=5, period=60)    # outermost — rate checked first
@decorators.owner_only                         # auth guard — checked second
@decorators.log_execution                      # innermost — logs after auth passes
async def cmd_transfer(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    ...
```

When there is no auth guard:

```python
@decorators.ratelimiter(limit=8, period=30)
@decorators.log_execution
async def cmd_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    ...
```

Message-event handlers (e.g. `on_new_member`) are exempt from rate limiters.

### Standard Rate Limits

| Category | limit | period |
|---|---|---|
| Destructive commands (ban, kick, unban, broadcast) | 3–5 | 60 |
| Moderation commands (mute, warn, cleanup) | 3–5 | 60 |
| Read commands (stats, groups, checkme, help) | 8 | 30 |
| Inline callbacks (button presses) | 15 | 30 |
| Emergency-only (leaveall) | 1 | 300 |

---

## Async Patterns

Use `asyncio.gather()` for any two or more independent async operations:

```python
# Good — parallel
executor_role, (target_id, fname) = await asyncio.gather(
    get_effective_role(admin.id),
    extraction.extract_target(update, args, ctx.bot),
)

# Bad — sequential
executor_role = await get_effective_role(admin.id)
target_id, fname = await extraction.extract_target(update, args, ctx.bot)
```

---

## Module File Structure

Every module file in `tcbot/modules/` must follow this structure:

```python
# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""One-line description of what this module does."""

from __future__ import annotations

# stdlib imports
# third-party imports
# internal imports

log = logging.getLogger(__name__)

__module_name__ = "Module Name"   # or None to hide from /help
__help_text__   = "..."           # omit if __module_name__ is None


# ── Section Divider ──────────────────────────────────────────────── #

@decorators.ratelimiter(limit=5, period=60)
@decorators.mod_only
@decorators.log_execution
async def cmd_example(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    ...


# ── Handlers ──────────────────────────────────────────────────────── #

__handlers__ = [...]
```

---

## What NOT To Do

- Do not add `from typing import List, Optional, Tuple` — use `list`, `int | None`, `tuple`
- Do not use `datetime.utcnow()` or inline `datetime.now(timezone.utc)` — use `tcbot.utils.timedate_format` only
- Do not use more than 3 emojis per message
- Do not add comments explaining what the next line obviously does
- Do not create duplicate render/keyboard functions across modules
- Do not inline imports inside function bodies
- Do not use `mention(x) + code(x)` pattern — pick one per context
- Do not use `q._bot` (private PTB attribute) — use `ctx.bot`
- Do not create `*_conv.py` files — ConversationHandlers belong in `*_flow.py`
- Do not duplicate reason/proof state handlers — use `reason_flow.build_modaction_conv()`
- Do not add packages to `requirements.txt` — managed via `pyproject.toml`
