# Code Style - TCF Bot

Before making any changes, **read all documentation files in the `agents/` directory** - specifically:
- `agents/RULES.md` - coding conventions, what is forbidden
- `agents/STYLE-CODE.md` - code style, typing, and formatting rules
- `agents/STYLE-COMMENTS.md` - comment and docstring style
- `agents/WORKFLOW.md` - branching, commit conventions, and deployment checklist
- `agents/CLAUDE.md` - project-specific guidance and gotchas
- `agents/REPLIT.md` - Replit environment, config, and secrets guidance

## Language and Runtime

- Python 3.13+
- Use built-in generic types: `list[str]`, `dict[str, int]`, `tuple[int, int | None]`
- Use `X | Y` union syntax, not `Optional[X]` or `Union[X, Y]`
- Always add `from __future__ import annotations` as the first non-comment line

## Imports

Order (enforced by isort):
1. `from __future__ import annotations`
2. Standard library
3. Third-party (`telegram`, `motor`, `flask`, etc.)
4. Internal (`tcbot.*`)

Group imports with one blank line between groups. Never inline imports inside function bodies.

## Naming

| Construct | Convention | Example |
|---|---|---|
| Module-level private | `_snake_case` | `_render()`, `_kb()` |
| Module-level constant | `_UPPER_CASE` | `_PAGE_SIZE`, `_HELP_INDEX_TEXT` |
| Class | `PascalCase` | `BanEnforcer`, `GroupHealthAgent` |
| Async handler | `cmd_*` or `on_*` | `cmd_ban_start`, `on_join_decision` |
| ConversationHandler state | `WAITING_*` | `WAITING_PROOF`, `WAITING_REASON` |

## Alignment

Align related assignment groups for readability:

```python
# Good
uid     = ban["banned_user_id"]
aid     = ban.get("admin_user_id", 0)
ban_id  = ban["ban_id"]

# Not preferred
uid = ban["banned_user_id"]
aid = ban.get("admin_user_id", 0)
ban_id = ban["ban_id"]
```

This applies to multi-line variable blocks, not single assignments.

## Section Dividers

Use the following style to separate logical sections. The title line must be exactly **70 characters** wide with the text centered and flanked by `#` and `─` characters.
The Section Title should be concise but descriptive of the content below. Use this style for major sections within a handler or function, but not for every minor block.

```python
# ────────────────────────── Section Title ───────────────────────── #
# ! WARNING: Short or Long Warning Description
# ! CRITICAL: Short or Long Critical Description
# TODO: Short or Long Description
# NOTE: Short or Long Note Description
# ? Short or Long Question Description
# * Short or Long Highlight or Information or General Description
```
or use a docstring for longer descriptions:
```python
# ────────────────────────── Section Title ───────────────────────── #
"""
! WARNING: Short or Long Warning Description
! CRITICAL: Short or Long Critical Description
! TODO: Short or Long Description
! NOTE: Short or Long Note Description
! ? Short or Long Question Description
! * Short or Long Highlight or Information or General Description
"""
```

Do not add comments that explain what the next line obviously does:
```python
# ! Bad
# * Get the user ID
uid = update.effective_user.id

# * Good - no comment needed, the code is self-evident
uid = update.effective_user.id
```

## String Formatting

- Use f-strings for all interpolation
- HTML responses use `esc()` for user-provided text, `mention()` for clickable names, `code()` for IDs and identifiers
- Multi-line strings use parenthesized concatenation, not backslash continuation:

```python
text = (
    "<b>Ban Information</b>\n\n"
    f"User: {mention(uid, fname)}\n"
    f"Ban ID: {code(ban_id)}"
)
```

## Error Handling

- Use `try/except Exception` only at I/O boundaries (Telegram API calls, DB writes)
- Always log errors: `log.error("Context: %s", exc)` or `log.warning(...)`
- Do not raise exceptions inside handlers - handle gracefully and reply to the user

## Dataclasses

Use `@dataclass` for result containers. Use `frozen=True` for config objects:

```python
@dataclass
class SweepResult:
    chat_id: int
    banned:  int = 0
    errors:  int = 0
```

## Decorator Order

Three layers in fixed order — **outermost to innermost**:

1. `@decorators.ratelimiter(limit, period)` — outermost; throttles per-user call rate
2. `@decorators.owner_only` / `@decorators.staff_only` / `@decorators.mod_only` / `@decorators.basic_mod_only` — auth guard
3. `@decorators.log_execution` — innermost; logs entry, exit, and elapsed ms after auth passes

```python
@decorators.ratelimiter(limit=5, period=60)    # * outermost  – rate checked first
@decorators.owner_only                         # * auth guard – checked second
@decorators.log_execution                      # * innermost  – logs after auth passes
async def cmd_transfer(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    ...
```

When there is no auth guard, ratelimiter and log_execution are used directly:

```python
@decorators.ratelimiter(limit=8, period=30)
@decorators.log_execution
async def cmd_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    ...
```

For ConversationHandler entry points decorated inside the conversation (e.g. `cmd_kick_entry`), apply the stack the same way — the ConversationHandler wraps the already-decorated function.

**Standard rate limits:**

| Category | limit | period |
|---|---|---|
| Destructive commands (ban, kick, unban, broadcast) | 3–5 | 60 |
| Moderation commands (mute, warn, cleanup) | 3–5 | 60 |
| Read commands (stats, groups, checkme, help) | 8 | 30 |
| Inline callbacks (button presses) | 15 | 30 |
| Emergency-only (leaveall) | 1 | 300 |

## Related documentation

- [Documentation hub](../docs/index.md)
- [Project architecture](../docs/architecture.md)
- [Modules and service boundaries](../docs/modules.md)
- [Conversation flows and workflows](../docs/workflows.md)
- [Development workflow and onboarding](../docs/development.md)
- [AI / agent guidelines](../docs/agent-guidelines.md)
