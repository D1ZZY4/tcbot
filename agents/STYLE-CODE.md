# Code Style — TCF Bot

## Language and Runtime

- Python 3.11+
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

Use `## ---` style comments to separate logical sections within a long file:

```python
## ── Section title ────────────────────────────────────────────────────────────
## Short escription
```

Do not add comments that explain what the next line obviously does:
```python
# Bad
# Get the user ID
uid = update.effective_user.id

# Good — no comment needed, the code is self-evident
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
- Do not raise exceptions inside handlers — handle gracefully and reply to the user

## Dataclasses

Use `@dataclass` for result containers. Use `frozen=True` for config objects:

```python
@dataclass
class SweepResult:
    chat_id: int
    banned:  int = 0
    errors:  int = 0
```
