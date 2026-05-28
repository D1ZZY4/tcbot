# Comment Style — TCF Bot

Read `agents/CLAUDE.md` first. This file defines comments, docstrings, and
section divider conventions for the project.

---

## Goals

Comments should explain intent, constraints, risks, or non-obvious behavior.
They should not restate the code. Prefer clear names and small functions over
large explanatory comments.

---

## Better Comments Prefixes

Use these prefixes in inline `#` comments and, when useful, inside docstrings.
They are designed for the Better Comments extension but remain readable without
it.

| Prefix | Use for |
|---|---|
| `# ! WARNING:` | Dangerous behavior, security-sensitive constraints |
| `# ! CRITICAL:` | Must-not-ignore correctness or safety rule |
| `# ?` | Question, uncertainty, or follow-up to verify |
| `# TODO:` | Deferred work with enough context to act |
| `# *` | Important note, highlight, or design intent |
| `# //` | Dead/commented-out code marker; remove instead of keeping |

Examples:

```python
# ! CRITICAL: This check prevents non-staff users from approving appeals.
# ? Should this use fan_out() after group count grows further?
# TODO: Add a migration once old ban documents no longer omit proof_link.
# * Telegram albums arrive as separate updates; debounce before final upload.
```

Rules:

- In `#` comments, use one space after `#`: `# !`, `# ?`, `# TODO:`, `# *`.
- `# !` must include `WARNING:` or `CRITICAL:`.
- TODOs must include enough context for a future maintainer.
- Do not use `# //` to temporarily disable code. Delete dead code.
- Do not use double-hash comments such as `## note` in Python modules.

---

## Docstrings

Module docstrings are required and single-line:

```python
"""Federation ban commands and handler registration."""
```

Function docstrings are used when the function's purpose, constraints, or return
shape are not obvious from the name and signature.

Preferred single-line docstring:

```python
async def active_bans() -> list[BanDoc]:
    """Return all active federation bans."""
```

Use multi-line docstrings only when annotations add real value:

```python
async def sweep_group(chat_id: int) -> tuple[int, int]:
    """
    Apply all active federation bans to one group.

    ! Must be called by a mod-only command path.
    * Returns (banned_count, error_count).
    TODO: Add dry-run mode for audit previews.
    """
```

Rules:

- Do not use Sphinx `:param:` / `:returns:` tags.
- Do not use Markdown tables inside Python docstrings.
- Do not add docstrings to trivial one-line helpers whose names are clear.
- Keep docstrings accurate when behavior changes.

---

## Section Dividers

Use section divider comments for top-level organization in medium and large
modules. Generate the bars with the Comment Divider extension when possible;
do not hand-type inconsistent widths.

Canonical divider levels:

```python
# ────────────────────────────────── H1 ───────────────────────────────── #
# ────────────────────────── H2 ────────────────────────── #
# ~~~~~~~~~~~~~~~~~~~ H3 ~~~~~~~~~~~~~~~~~~~~ #
# ~~~~~~~~~~~ H4 ~~~~~~~~~~~ #
```

Usage:

| Level | Use |
|---|---|
| H1 | Top-level module sections |
| H2 | Major blocks inside a long section |
| H3 | Sub-groups or per-entity blocks |
| H4 | Rare minor grouping |

Default to H1 for module-level sections.

Common section names:

```python
# ─────────────────────────────── Handlers ───────────────────────────── #
# ─────────────────────────────── Commands ───────────────────────────── #
# ─────────────────────────────── Retrieval ──────────────────────────── #
# ─────────────────────────────── Mutations ──────────────────────────── #
# ─────────────────────────────── Role CRUD ──────────────────────────── #
# ─────────────────────────── Role Resolution ────────────────────────── #
# ─────────────────────────── Collection Helpers ─────────────────────── #
# ─────────────────────────────── Utilities ──────────────────────────── #
```

Do not add dividers to very small modules when simple spacing is enough.

---

## Inline Comments

Good inline comments explain why:

```python
# * Album media groups arrive as separate updates, so wait briefly before upload.
await asyncio.sleep(cfg.album_debounce)
```

Bad inline comments restate what:

```python
# Bad: get the user ID.
uid = update.effective_user.id
```

Rules:

- Keep comments short and close to the code they explain.
- Update or remove comments when code changes.
- Avoid comments that describe obvious assignments, imports, or returns.
- Prefer a helper function with a clear name over a long inline comment.

---

## Comments for Constants

Add a `# *` comment above non-obvious module constants:

```python
# * Telegram API fan-out is bounded to avoid flooding and pool exhaustion.
_MAX_CONCURRENT = 10
```

Do not comment obvious constants:

```python
_PAGE_SIZE = 10
```

---

## Handler Export Comments

Use labels around `__handlers__` only when they improve readability:

```python
# ─────────────────────────────── Handlers ───────────────────────────── #

_BAN_CMDS   = build_prefixed_filters("tcban")
_UNBAN_CMDS = build_prefixed_filters("tcunban")

__handlers__ = [
    ban_conversation(cmd_ban_start, _BAN_CMDS),
    MessageHandler(_UNBAN_CMDS, cmd_unban),
]
```

Avoid noisy comments like `# Register handlers` directly above an obvious
`__handlers__` assignment.

---

## Markdown Documentation Style

For files under `agents/` and `docs/`:

- Write in English only.
- Prefer concise headings and bullets.
- Use fenced code blocks with language tags when helpful.
- Use project-relative paths in backticks.
- Do not include real credentials, private chat IDs, or production-only links.
- Keep docs aligned with `agents/CLAUDE.md` as the source of truth.

---

## What Not To Do

- Do not comment out dead code.
- Do not add vague TODOs such as `# TODO: fix later`.
- Do not use Sphinx-style docstring tags.
- Do not explain obvious code.
- Do not hand-type malformed section dividers.
- Do not add comments that contradict `agents/CLAUDE.md` or `agents/RULES.md`.
