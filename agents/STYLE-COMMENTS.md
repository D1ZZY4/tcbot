# Comment Style — TCF Bot

**Read `agents/CLAUDE.md` first.** This file defines all comment and docstring conventions for the project.

Compatible with: Replit AI, Claude, Gemini, Qwen, GitHub Copilot, and any AI coding agent.

---

## VS Code Extensions (Required)

This project uses two VS Code extensions that define comment visual style:

- **Better Comments** — color-codes annotation prefixes in `#` comments and docstrings
- **Comment Divider** — generates section divider bars at consistent widths

All conventions in this file are designed to render correctly with these extensions.

---

## Better Comments — Annotation Prefixes

Better Comments recognizes these annotation prefixes and highlights them with distinct colors.
They work in two contexts: **inline `#` comments** and **inside docstrings** (requires `"better-comments.multilineComments": true`).

| Prefix | Color | Use for |
|---|---|---|
| `!` | 🔴 Red | Warnings, critical notes, dangerous behavior |
| `?` | 🔵 Blue | Questions, uncertainties, things to verify |
| `TODO:` | 🟠 Orange | Deferred tasks |
| `*` | 🟢 Green | Highlights, info, general descriptions |
| `//` | ~~Grey~~ | Dead/commented-out code that should be removed |

### In inline `#` comments

Prefix immediately after `# ` with one space:

```python
# ! WARNING: This bypasses rate limiting — only call from trusted contexts
# ! CRITICAL: Removing this check will allow unauthenticated access

# ? Should this use asyncio.gather()? Check PTB thread safety first

# TODO: batch ban calls with asyncio.gather() once rate-limit handling is stable

# * Sliding-window rate limiter for commands: 8 calls per 30 seconds
_cmd_limiter = _RateLimiter(max_calls=8, window=30.0)

# // uid = update.message.from_user.id  ← old extraction pattern, do not use
```

### In docstrings (multiline)

Same prefixes, no `#` — placed on their own line inside the triple-quoted block:

```python
async def sweep_group(chat_id: int) -> tuple[int, int]:
    """
    Ban all federation-banned members in chat_id.

    * Returns (banned_count, error_count).
    ! Caller must hold mod_only permission before invoking.
    ? Consider adding a dry-run mode for auditing.
    TODO: add per-group concurrency cap once PTB supports it.
    """
```

Use docstring annotations sparingly — only when the detail is important enough to appear inline with the function signature rather than in a nearby `#` comment.

**Rules:**
- In `#` comments: always one space between `#` and the prefix: `# !`, `# *`, `# ?`, `# TODO:`, `# //`
- In docstrings: prefix is the first non-whitespace character on the line
- `# //` is for dead code only — not for temporarily disabling logic
- `# !` includes the label inline: `# ! WARNING: ...` or `# ! CRITICAL: ...`

---

## Section Dividers — Comment Divider Extension

Use Comment Divider bar styles to separate logical sections. Four levels available:

```python
# ────────────────────────────────── H1 ───────────────────────────────── #   ← file-level / top-level section
# ────────────────────────── H2 ────────────────────────── #                  ← major block within a section
# ~~~~~~~~~~~~~~~~~~~ H3 ~~~~~~~~~~~~~~~~~~~~ #                               ← sub-block or grouping
# ~~~~~~~~~~~ H4 ~~~~~~~~~~~ #                                                ← minor grouping
```

### When to use each level

| Level | Use for |
|---|---|
| H1 | Top-level sections in a module file (e.g., `Handlers`, `Mutations`, `Role CRUD`) |
| H2 | Major blocks within a long section |
| H3 | Sub-groupings (e.g., per-role helpers, per-entity block) |
| H4 | Minor groupings — rarely needed |

**Default to H1 for all module-level sections.** Always generate dividers with the Comment Divider extension — never hand-type them.

### Common section names (use consistently)

```python
# ─────────────────────────────── Handlers ───────────────────────────── #
# ──────────────────────────────── Role CRUD ─────────────────────────── #
# ─────────────────────────── Role Resolution ────────────────────────── #
# ────────────────────────────────── Retrieval ───────────────────────── #
# ─────────────────────────────── Mutations ──────────────────────────── #
# ──────────────────────────────── Statistics ────────────────────────── #
# ──────────────────────────────── Module & Help ─────────────────────── #
# ─────────────────────────────── Entry point ────────────────────────── #
# ──────────────────────────── Collection Helpers ────────────────────── #
```

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

The docstring is a single sentence ending with a period. Always single-line — never multi-line (use docstring annotations for extended notes if needed).

---

## Function Docstrings

Write docstrings only when the function's purpose is **not immediately obvious** from its name and signature. Default to a single-line form. Use the multi-line annotation form only when you need to add `!`, `?`, or `TODO:` notes alongside the description.

```python
# Single-line (preferred when no annotations needed)
async def sweep_group(chat_id: int) -> tuple[int, int]:
    """Ban all federation-banned members in chat_id; returns (banned, errors)."""

# Multi-line (use when annotations add value)
async def sweep_group(chat_id: int) -> tuple[int, int]:
    """
    Ban all federation-banned members in chat_id; returns (banned, errors).

    ! Must be called with mod_only permission — no internal auth check.
    TODO: add dry-run mode for audit reports.
    """
```

Do not use `:param:` / `:returns:` Sphinx tags. Do not use Sphinx double-backtick notation. Write plain text.

Obvious helper functions do not need docstrings:

```python
def _strip_chat_id(chat_id: int) -> str:
    return str(chat_id).replace("-100", "")
```

---

## Inline Comments

Keep inline comments brief. Use Better Comments prefixes from the table above.

Do not comment what the code already says:

```python
# Bad
# * Get the user ID
uid = update.effective_user.id

# Good — no comment needed
uid = update.effective_user.id
```

---

## Module-Level Constants

Add a `# *` comment above non-obvious module-level constants:

```python
# * Telegram allows 30 msg/s globally; 10 concurrent is safe and fast.
_MAX_CONCURRENT: int = 10

# * Sliding-window rate limiter for commands: 8 calls per 30 seconds.
_cmd_limiter = _RateLimiter(max_calls=8, window=30.0)
```

---

## Handler `__handlers__` Export

Add labels only if the pattern is not self-evident:

```python
# * Straightforward — no comment needed
_KICK_CMDS = build_prefixed_filters("tckick") | build_prefixed_filters("tck")
__handlers__ = [kick_conversation(cmd_kick_entry, _KICK_CMDS)]

# * Multiple handlers benefit from labels
_MUTE_CMDS   = build_prefixed_filters("tcmute") | build_prefixed_filters("tcm")
_UNMUTE_CMDS = build_prefixed_filters("tcunmute") | build_prefixed_filters("tcunm")

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
- Do not add section dividers at the wrong width — use Comment Divider to generate them
- Do not write docstrings on trivial one-liners whose name explains everything
- Do not leave `# TODO:` comments without enough context to act on them
- Do not use `# //` for temporarily disabling logic — dead code must be removed