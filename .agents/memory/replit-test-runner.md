---
name: Replit test runner
description: How to run tests and ruff in this Replit environment; correct uv commands to use.
---

## Test runner command

```bash
uv run --extra test pytest tests/ -q
```

`uv run --extra test pytest` is the canonical way. Bare `pytest` or `python3 -m pytest` fail because pytest is only available as an `--extra test` dependency.

**Why:** Packages install under Python 3.12 via uv. pytest is declared only in `[project.optional-dependencies.test]`, so `--extra test` is required.

## Ruff

```bash
uv run ruff format .
uv run ruff check --fix .
```

Ruff is declared in `[dependency-groups] dev = ["ruff"]` in `pyproject.toml`. `uv sync` installs it automatically so `uv run ruff` works without any extra flags or `uvx`. Do NOT use `uvx ruff`.

## Baseline (2026-06-06, session 13)

- 1405 tests across 71 files, all passing, **0 warnings**.
- `uv run ruff check .` clean, `uv run ruff format --check .` clean.
- Pre-existing "coroutine '_send_one' was never awaited" warnings in test_broadcasting.py resolved
  by replacing `AsyncMock(return_value=...)` with `_make_fan_out_mock(n)` helper that drains coroutines.

## How to apply

Always use `uv run --extra test pytest` for tests and `uv run ruff` for linting. Never use bare `pytest`, `uvx ruff`, or `uv run ruff --extra dev`.
