# Comment Style — TCF Bot

## Module Docstring

Every file starts with the copyright header, then a one-line module docstring:

```python
# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

## Short description of what this module does.


from __future__ import annotations
```

The docstring is a single sentence. No period needed for one-liners.
Multi-line docstrings are allowed for complex modules (e.g. mute_flow.py with its flow diagram).

## Function Docstrings

Write docstrings only when the function's purpose is not immediately obvious from its name and signature.
Keep them concise — one sentence or a short paragraph. No `:param:` / `:returns:` Sphinx tags.

```python
async def sweep_group(self, chat_id: int) -> tuple[int, int]:
    """
    Ban all currently-present federation-banned members in `chat_id`.

    Returns (banned_count, error_count). Individual errors do not abort
    the sweep.
    """
```

Obvious helper functions do not need docstrings:
```python
def _strip_chat_id(chat_id: int) -> str:
    return str(chat_id).replace("-100", "")
```

## Inline Comments

Use `##` (double hash) for section-level inline comments. Use `#` only for brief end-of-line notes.

```python
## Apply all existing federation bans
bans = await db.bans_db.active_bans()
applied = 0
for ban in bans:
    ...
```

Do not comment what the code already says:
```python
# Bad
# Increment applied counter
applied += 1

# Good — no comment needed
applied += 1
```

## TODO / FIXME

Use `## TODO:` for deferred improvements. Include enough context to act on it:
```python
## TODO: batch ban calls with asyncio.gather() once rate-limit handling is in place
for grp in groups:
    await bot.ban_chat_member(grp["chat_id"], target_id)
```

## Section Dividers

Use dashed dividers to separate major logical blocks in longer files:
```python
## ── Section title ────────────────────────────────────────────────────────────
## Short description
```

Keep dividers consistent in length (75 dashes). Do not use them for every 5-line block —
only for genuinely distinct sections (e.g. keyboard builders vs. handlers vs. handler factory).

## What Not To Comment

- Do not comment imports
- Do not add "Legacy compat" or "Deprecated" blocks — remove dead code outright
- Do not explain Python syntax
- Do not add `# noqa` without a reason in the same comment
