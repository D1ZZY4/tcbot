---
name: python-code-quality
description: Use when formatting, linting, typing, or reviewing Python quality in TCBot with Python 3.12, Ruff, uv, and the project's handler/database conventions.
---
Last updated: 2026-05-29


# Python Code Quality for TCBot

Before invoking this skill, confirm the read/update rules in [`.agents/CLAUDE.md`](../../CLAUDE.md#mandatory-read-these-files-before-any-work). After any code change, update [`CHANGELOG.md`](../../../CHANGELOG.md) and the matching `docs/*.md` in the same turn.

Use this skill when improving or validating Python code quality in the TCF Bot repository. The project uses Python 3.12, `uv`, and Ruff. It does not currently configure a separate type checker in `pyproject.toml`, so type-quality guidance should focus on clear annotations, Ruff-compatible style, and practical review rather than inventing a type-check command.

## When to Use This Skill

Use this skill when the task mentions or involves:

- Ruff formatting or lint diagnostics.
- Python import sorting, unused imports, unused variables, or syntax modernization.
- Type annotations, `TypedDict`, `NewType`, or handler signatures.
- Code review for maintainability, duplication, or project convention compliance.
- Preparing validation commands after a code change.

If the task edits bot runtime code, also apply the project policy skill before changing code.

## Current Project Tooling

From `pyproject.toml` as of 2026-06-11:

```toml
[project]
requires-python = ">=3.12"
dependencies = [
    "python-telegram-bot[rate-limiter]",
    "motor",
    "flask",
    "python-dotenv",
]

[dependency-groups]
dev = ["ruff"]

[tool.ruff]
line-length = 88
target-version = "py312"
exclude = [".local/", ".agents/", ".kilo/", ".trae/", ".claude/", "attached_assets/"]

[tool.ruff.lint]
select = ["B", "C4", "D", "E4", "E7", "E9", "F", "FBT", "I", "PERF", "PIE", "PLC", "PLE", "PTH", "RET", "RUF", "SIM", "TC", "TRY400", "TRY401", "UP", "W"]
```

Ruff is in `[dependency-groups] dev` (PEP 735), installed automatically by `uv sync`. Use `uv run ruff format .` and `uv run ruff check .` directly; `uvx ruff` is not needed.

Do not claim `mypy`, `pyright`, or `ty` validation exists unless it is added to the project.

## Standard Commands

Install dependencies:

```bash
uv sync
```

Format:

```bash
uv run ruff format .
```

Lint:

```bash
uv run ruff check .
```

Auto-fix safe lint issues:

```bash
uv run ruff check --fix .
```

Recommended source-change validation order:

```bash
uv run ruff format .
uv run ruff check --fix .
```

For documentation-only or skill-only changes, Python validation is usually unnecessary unless Python snippets or project commands were changed.

## Code Style Priorities

Project-specific conventions take precedence over generic style advice.

- Python 3.12 syntax.
- `from __future__ import annotations` as the first non-comment line in Python modules.
- Built-in generics: `list[str]`, `dict[str, int]`, `tuple[int, ...]`.
- Union operator: `str | None`, not `Optional[str]`.
- No wildcard imports.
- Avoid inline imports.
- Four-space indentation.
- Ruff-formatted line wrapping, with current configured line length of 88.
- HTML-only Telegram messages with escaped user-provided text.
- UTC timestamps through `tcbot.utils.timedate_format`.
- Database writes through `tcbot/database/*_db.py` helpers, not handlers.

## Import Organization

Use this order:

1. `from __future__ import annotations`
2. Standard library imports.
3. Third-party imports.
4. First-party `tcbot.*` imports.

```python
from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes, MessageHandler

from tcbot.modules.helper import decorators
from tcbot.utils.prefixes import build_prefixed_filters
```

Ruff's `I` rules should handle sorting. Do not fight the formatter with manual spacing unless the project policy explicitly requires alignment in a specific context.

## Type Annotation Guidance

Annotate public helpers, database helpers, and handler functions. Prefer domain types already provided by the project where available.

```python
from __future__ import annotations

from typing import Literal, TypedDict

RoleName = Literal["founder", "admin", "developer", "tester"]


class RoleDocument(TypedDict):
    user_id: int
    role: RoleName
    assigned_by: int
```

Good patterns:

- Use `TypedDict` for Mongo document shapes that are read in several places.
- Use `Literal` for constrained string fields such as roles and statuses.
- Use `NewType` domain primitives from project database type modules when available.
- Return `None` explicitly for not-found lookups: `dict[str, object] | None`.
- Keep handler return type `None` unless the framework requires otherwise.

Avoid:

- `Any` as a shortcut for unclear data shapes.
- `cast()` to silence a problem that should be modeled or checked.
- Type comments from older Python versions.
- Adding a new type checker without updating project configuration and documentation.

## Handler Quality Checklist

For `tcbot/modules/*.py` handlers:

- Handler names use `cmd_*` for commands and `on_*` for events.
- Command handlers use the required decorator stack when applicable.
- `__module_name__`, `__help_text__`, and `__handlers__` are present for modules.
- User-facing text uses `parse_mode="HTML"`.
- User-provided values are escaped through formatter helpers.
- Callback queries call `await query.answer()` before other actions.
- The handler delegates persistence to `tcbot.database` helpers.
- Multi-group fan-out uses `tcbot.utils.dispatch.fan_out()`.
- No `print()`; use module loggers.

## Database Helper Quality Checklist

For `tcbot/database/*_db.py` helpers:

- Async functions with explicit parameter and return types.
- Clear function names: `get_*`, `add_*`, `update_*`, `delete_*`, `list_*`.
- No Telegram object types in the database layer.
- Queries match existing indexes, or index setup is updated with the new access pattern.
- MongoDB field additions are backward-compatible.
- Callers do not receive raw Motor cursor objects unless there is a deliberate streaming need.

## Ruff Diagnostics Triage

Common enabled diagnostics in this project:

- `F401`: unused import. Remove it unless it is part of a documented public API.
- `F841`: unused local variable. Remove it or use the value meaningfully.
- `I001`: imports are unsorted. Let `ruff check --fix` or `ruff format` correct it.
- `E4`, `E7`, `E9`: syntax/indentation/runtime parse problems. Fix manually.

Because the current Ruff selection is intentionally narrow, do not assume Ruff will catch every style issue. Apply project rules during review.

## Safe Auto-Fix Policy

Safe to auto-fix:

- Import sorting.
- Removing unused imports.
- Formatting changes from Ruff.
- Simple unused variable cleanup when the variable has no side effect and is not needed.

Review manually:

- Deleting unused functions or modules.
- Changing database field names or document shapes.
- Changing handler registration.
- Rewriting exception handling.
- Modifying user-facing moderation behavior.

Never remove meaningful code only to silence a diagnostic.

## Documentation and Skill-Only Changes

For Markdown-only changes in `.agents/skills/`, validate mentally unless the content includes executable examples that should be syntax-checked. Ensure each skill has YAML frontmatter with:

- `name` matching the skill directory.
- An actionable `description` explaining when to use it.
- Valid YAML syntax.

Avoid stale generic references, outdated Python versions, unrelated frameworks, or commands not configured for this project.

## References

- Ruff documentation: https://docs.astral.sh/ruff/
- Python typing documentation: https://docs.python.org/3/library/typing.html
- Project-specific reference: `tgbot/.agents/skills/python-code-quality/REFERENCE.md`
