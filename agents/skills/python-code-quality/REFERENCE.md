# Python Code Quality — TCBot Reference

Updated: 2026-05-28

This reference supports the `python-code-quality` skill for the TCF Bot repository. It reflects the current project stack: Python 3.12, `uv`, Ruff, pytest, pytest-asyncio, `python-telegram-bot` 22.5, Motor/MongoDB, and Flask keepalive.

## Tooling Snapshot

Current `pyproject.toml` essentials:

```toml
[project]
requires-python = ">=3.12"

[tool.ruff]
line-length = 88
target-version = "py312"

[tool.ruff.lint]
select = ["E4", "E7", "E9", "F", "I"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
addopts = "-ra -q"
```

Ruff currently enforces syntax/pyflakes/import-order rules, not a full strict style suite. Apply project conventions manually during review.

## Commands

Install dependencies:

```bash
uv sync
```

Install test extras:

```bash
uv sync --extra test
```

Run all tests:

```bash
uv run --extra test pytest tests/ -v
```

Run one test file:

```bash
uv run --extra test pytest tests/test_decorators.py -v
```

Collect tests only:

```bash
uv run --extra test pytest --collect-only -q
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

## Test Quality

Tests should remain offline and deterministic.

Good test targets:

- Database helper behavior.
- Formatter escaping and message construction.
- Decorator authorization behavior.
- Conversation state transitions.
- Callback data parsing.
- Partial failure handling for fan-out.
- Datetime helper behavior.

Avoid tests that require:

- A real Telegram bot token.
- A real MongoDB server.
- Network access.
- Wall-clock sleeps longer than necessary.
- Test ordering assumptions.

## Async Test Example

```python
async def test_callback_answers_query(fake_update, fake_context) -> None:
    query = fake_update.callback_query

    await handler.on_decision(fake_update, fake_context)

    query.answer.assert_awaited_once()
```

Prefer assertions against observable behavior: database helper calls, Telegram API mock calls, returned state constants, and message text.

## Review Strategy

For a code-quality pass:

1. Read the owning module and nearby helpers first.
2. Run the most focused test or diagnostic available.
3. Fix root causes, not only symptoms.
4. Run Ruff formatting/import cleanup after code edits.
5. Re-run focused validation, then broader validation if the change touches shared behavior.
6. Report any unrelated pre-existing failures separately.

## Skill and Markdown Quality

For `agents/skills/*/SKILL.md` files:

- Frontmatter begins and ends with `---`.
- `name` exactly matches the skill directory.
- `description` is actionable and says when to use the skill.
- Content is project-specific and current.
- Avoid global, generic, unrelated, or outdated tool claims.
- Keep tone professional-friendly and concise enough to scan.

## References

- Ruff: https://docs.astral.sh/ruff/
- pytest: https://docs.pytest.org/
- pytest-asyncio: https://pytest-asyncio.readthedocs.io/
- Python typing: https://docs.python.org/3/library/typing.html
- uv: https://docs.astral.sh/uv/
