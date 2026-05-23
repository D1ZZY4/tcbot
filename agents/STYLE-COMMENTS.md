# Comment Style — TCF Bot

**Read `agents/CLAUDE.md` first.** This file defines all comment and docstring conventions for the project.

Compatible with: Replit AI, Claude, Gemini, Qwen, GitHub Copilot, and any AI coding agent.

---

## File Header

Every file starts with the copyright header followed by a one-line module docstring:

```python
# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""One-line description of what this module does."""

from __future__ import annotations
```

The docstring is a single sentence ending with a period. Always single-line — never multi-line.

---

## Function Docstrings

Write docstrings only when the function's purpose is **not immediately obvious** from its name and signature. Always single-line. Do not use `:param:` / `:returns:` Sphinx tags. Do not use Sphinx double-backtick notation (``X``) — write plain text.

```python
async def sweep_group(chat_id: int) -> tuple[int, int]:
    """Ban all federation-banned members in chat_id; returns (banned, errors)."""
```

Obvious helper functions do not need docstrings:

```python
def _strip_chat_id(chat_id: int) -> str:
    return str(chat_id).replace("-100", "")
```

---

## Inline Comments

Use `#` for brief end-of-line notes and section-level annotations.

Annotation prefixes for inline comments:

```python
# ! WARNING: description
# ! CRITICAL: description
# TODO: description
# NOTE: description
# ? question
# * highlight, info, or general description
```

Do not comment what the code already says:

```python
# Bad
# * Increment applied counter
applied += 1

# Good — no comment needed
applied += 1
```

Do not add comments that restate the function name or the line of code:

```python
# Bad
# * Get the user ID
uid = update.effective_user.id

# Good — no comment
uid = update.effective_user.id
```

---

## Section Dividers

Use this format to separate logical sections. The title line must be exactly **70 characters** wide with the text centered and flanked by `#` and `─` characters:

```python
# ────────────────────────── Section Title ───────────────────────── #
```

Use section dividers for major logical blocks within a file. Do not add them for every small group of lines.

Common section names (follow these conventions):

```python
# ─────────────────────── Collection Helpers ─────────────────────── #
# ────────────────────────── Role CRUD ───────────────────────────── #
# ─────────────────────── Role Resolution ────────────────────────── #
# ──────────────────────────── Retrieval ─────────────────────────── #
# ──────────────────────────── Mutations ─────────────────────────── #
# ─────────────────────────── Statistics ─────────────────────────── #
# ──────────────────────── Module & Help ─────────────────────────── #
# ───────────────────────── Entry point ──────────────────────────── #
# ───────────────────────── Handlers ─────────────────────────────── #
```

---

## TODO Comments

Use `# TODO:` for deferred improvements. Include enough context to act on it:

```python
# TODO: batch ban calls with asyncio.gather() once rate-limit handling is stable
for grp in groups:
    await bot.ban_chat_member(grp["chat_id"], target_id)
```

---

## Module-Level Constants and Registry Variables

Add a brief `# *` comment above non-obvious module-level constants:

```python
# * Telegram allows 30 msg/s globally; 10 concurrent is safe and fast.
_MAX_CONCURRENT: int = 10

# * Sliding-window rate limiter for commands: 8 calls per 30 seconds.
_cmd_limiter = _RateLimiter(max_calls=8, window=30.0)
```

---

## Handler `__handlers__` Export

The `__handlers__` list should have a brief comment only if the pattern is not self-evident:

```python
# * Example: straightforward, no comment needed
_KICK_CMDS = build_prefixed_filters("tckick") | build_prefixed_filters("tck")
__handlers__ = [kick_conversation(cmd_kick_entry, _KICK_CMDS)]

# * Example: multiple handlers benefit from labels
_MUTE_CMDS   = build_prefixed_filters("tcmute") | build_prefixed_filters("tcm")
_UNMUTE_CMDS  = build_prefixed_filters("tcunmute") | build_prefixed_filters("tcunm")

__handlers__ = [
    mute_conversation(cmd_mute_start, _MUTE_CMDS, escape_filter=_UNMUTE_CMDS),
    MessageHandler(_UNMUTE_CMDS, cmd_unmute),
]
```

---

## What NOT To Do

- Do not use `##` double-hash for regular inline comments — use `#`
- Do not write Sphinx-style `:param:` / `:returns:` tags
- Do not comment what the next line obviously does
- Do not add section dividers that are shorter or longer than 70 characters
- Do not write docstrings on trivial one-liners whose name explains everything
- Do not leave `TODO` comments without enough context to act on them
