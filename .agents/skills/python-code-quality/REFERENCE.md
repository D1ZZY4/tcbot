# Python Code Quality: TCBot Reference

For the parent skill instructions, see [`SKILL.md`](SKILL.md). For the canonical project rules this reference enforces, see [`../../CLAUDE.md`](../../CLAUDE.md) and [`../../RULES.md`](../../RULES.md).

Updated: 2026-06-11

This reference supports the `python-code-quality` skill for the TCF Bot repository. It reflects the current project stack: Python 3.12, `uv`, Ruff, `python-telegram-bot` (latest), Motor/MongoDB, and Flask keepalive.

## Tooling Snapshot

Current `pyproject.toml` essentials:

```toml
[project]
requires-python = ">=3.12"

[tool.ruff]
line-length = 88
target-version = "py312"
exclude = [".local/", ".agents/", ".kilo/", ".trae/", ".claude/"]

[tool.ruff.lint]
select = ["B", "C4", "D", "E4", "E7", "E9", "F", "FBT", "I", "PERF", "PIE", "PLC", "PLE", "PTH", "RET", "RUF", "SIM", "TC", "TRY400", "TRY401", "UP", "W"]
```

Ruff enforces a broad suite: pyflakes/syntax (`E`, `F`), import order (`I`), bugbear (`B`), comprehensions (`C4`), pydocstyle (`D`), boolean-trap (`FBT`), performance (`PERF`), misc (`PIE`), Pylint error/convention (`PLE`, `PLC`), pathlib (`PTH`), returns (`RET`), Ruff-specific (`RUF`), simplify (`SIM`), type-checking imports (`TC`), targeted try rules (`TRY400`, `TRY401`), pyupgrade (`UP`), and warnings (`W`). See `.agents/RUFF.md` for the canonical list and per-rule ignores. Apply remaining project conventions manually during review.

## Commands

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

## Python Module Checklist

For Python source files, verify:

- `from __future__ import annotations` is the first non-comment line.
- Imports are grouped: standard library, third-party, `tcbot.*`.
- No wildcard imports.
- No unnecessary inline imports.
- Public helpers and database helpers have return annotations.
- Async handlers return `None` unless a framework API requires a value.
- `logging.getLogger(__name__)` is used instead of `print()`.
- User-visible Telegram output uses `parse_mode="HTML"`.
- User-provided text is escaped.
- Datetimes use `tcbot.utils.timedate_format` helpers.

## Type Patterns

Use Python 3.12 style:

```python
from __future__ import annotations

from typing import Literal, TypedDict

Status = Literal["pending", "approved", "denied"]


class AppealDocument(TypedDict, total=False):
    appeal_id: str
    user_id: int
    status: Status
    reason: str
```

Prefer:

- `list[str]` over `List[str]`.
- `str | None` over `Optional[str]`.
- `dict[str, object]` for broad external data only when no narrower shape is practical.
- `TypedDict` for Mongo documents shared across modules.
- `Literal` for constrained strings.

Avoid:

- `Any` without a clear boundary reason.
- Type comments.
- Importing old typing aliases solely for Python versions below 3.12.

## Ruff Rule Notes

Enabled rule families:

| Family | Catches |
|---|---|
| `E4` | Import and module-level syntax/format issues |
| `E7` | Statement syntax and structure issues |
| `E9` | Runtime syntax errors detected by pycodestyle |
| `F` | Pyflakes issues such as undefined names and unused imports |
| `I` | Import ordering |

Common fixes:

- `F401`: remove unused imports unless part of a public re-export.
- `F821`: import or define the missing name; do not silence it.
- `F841`: remove unused locals or use the value meaningfully.
- `I001`: run `uv run ruff check --fix .`.

## Review Strategy

For a code-quality pass:

1. Read the owning module and nearby helpers first.
2. Run the most focused diagnostic available.
3. Fix root causes, not only symptoms.
4. Run Ruff formatting/import cleanup after code edits.
5. Re-run focused validation, then broader validation if the change touches shared behavior.
6. Report any unrelated pre-existing issues separately.

## Skill and Markdown Quality

For `.agents/skills/*/SKILL.md` files:

- Frontmatter begins and ends with `---`.
- `name` exactly matches the skill directory.
- `description` is actionable and says when to use the skill.
- Content is project-specific and current.
- Avoid global, generic, unrelated, or outdated tool claims.
- Keep tone professional-friendly and concise enough to scan.

## References

- Ruff: https://docs.astral.sh/ruff/
- Python typing: https://docs.python.org/3/library/typing.html
- uv: https://docs.astral.sh/uv/
