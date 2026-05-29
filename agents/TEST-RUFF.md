# Testing and Ruff — TCF Bot

Read [`CLAUDE.md`](CLAUDE.md) first. This file defines validation commands and quality checks for the project. For code style enforced by Ruff, see [`STYLE-CODE.md`](STYLE-CODE.md). For development workflow, see [`WORKFLOW.md`](WORKFLOW.md). For CI/CD that runs these commands automatically, see [`../docs/workflows-guide.md`](../docs/workflows-guide.md).

---

## Tooling

- Dependency manager: `uv`.
- Test runner: `pytest` with `pytest-asyncio`.
- Formatter/linter: Ruff.
- Python target: 3.12.
- Tests are designed to run offline without a real Telegram token or MongoDB
  connection.

Install runtime dependencies:

```bash
uv sync
```

Install test extras:

```bash
uv sync --extra test
```

---

## Test Commands

Run the full suite:

```bash
python3 -m pytest tests/ -v
```

Equivalent through `uv` with test extras:

```bash
uv run --extra test pytest tests/ -v
```

Collect tests only:

```bash
python3 -m pytest --collect-only -q tests/
```

Windows note: if `python3` is unavailable, use `python` or `uv run` with the
project environment.

---

## Ruff Commands

Format all files:

```bash
uv run ruff format .
```

Lint and apply safe fixes:

```bash
uv run ruff check --fix .
```

Check without modifying files:

```bash
uv run ruff check .
```

Ruff settings live in `pyproject.toml`. Keep source compatible with that file
rather than relying on editor-specific settings.

---

## Recommended Validation by Change Type

| Change type | Minimum validation |
|---|---|
| Documentation-only | Read changed docs; optionally run Markdown preview or spell check |
| Formatter/comment-only code change | `uv run ruff format .` and focused tests if behavior may be touched |
| Command handler change | Focused tests if available, then `python3 -m pytest tests/ -v` |
| Database helper change | Relevant DB tests plus full test suite |
| Workflow change | Relevant workflow tests plus full test suite |
| Dependency/config change | `uv sync`, Ruff, full test suite |

Do not claim validation passed unless the command ran and exited successfully.
If validation cannot run, report the exact command and error.

---

## Offline Test Requirements

Tests must not require:

- A real Telegram bot token.
- A real MongoDB connection.
- Network access.
- Replit-specific environment variables.
- Production chat IDs or private links.

Use mocks, fakes, and fixtures in `tests/conftest.py` where shared setup is
needed. Avoid duplicating fixture logic across test files.

---

## What to Test

Add or update tests when changing:

- Database helpers.
- Role resolution or permission checks.
- Decorators and rate limiting.
- Target extraction and parsing.
- Formatter, link, keyboard, and log-message helpers.
- Conversation workflow state transitions.
- Ban, appeal, warning, mute, kick, or promotion behavior.
- Datetime helper behavior.

Prefer focused, deterministic tests around pure helper logic where possible.
Mock Telegram API calls and Motor calls.

---

## Current Test Areas

The repository contains tests for areas such as:

- Appeal pure logic.
- Ban flow buffering and state behavior.
- Ban DB helper behavior.
- Config parsing.
- Decorators and execution logging.
- Formatting and parse-link helpers.
- Keyboard factory output.
- Log message templates.
- Prefix and command parsing.
- Rate limiter behavior.
- Target extraction helpers.
- User resolver behavior.
- Warning flows and warning DB helpers.

If the exact test count matters, verify it with `pytest --collect-only` instead
of relying on a hardcoded number in documentation.

---

## Common Failure Handling

1. Read the first failure carefully; fix the root cause, not the symptom.
2. If a failure is caused by your change, fix it before finalizing.
3. If a pre-existing unrelated failure appears, report it clearly with the
   command output and continue only if the task can still be completed safely.
4. Do not delete meaningful tests to make the suite pass.
5. Do not weaken assertions unless the expected behavior has intentionally
   changed and the new behavior is documented.

---

## Final Reporting

When finishing a task, include:

- Files changed.
- Validation commands run.
- Whether each command passed, failed, or could not run.
- Any remaining known issues or follow-up recommendations.
