---
name: Replit test runner
description: How to run tests and ruff in this Replit environment; correct uv commands to use.
---

## Test runner command

```bash
uv run --extra test pytest tests/ -q
```

`uv run --extra test pytest` is the canonical way. `python3.11` does not exist; bare `pytest` or `python3 -m pytest` fail because pytest is only available as an `--extra test` dependency.

**Why:** Packages install correctly under Python 3.12 via uv. The old workaround (PYTHONPATH + python3.11) was from a stale state and no longer applies.

## Ruff

```bash
uvx ruff format .
uvx ruff check --fix .
```

`uv run ruff` fails because ruff is in the `dev` optional group, not the default venv. `uvx` always works.

## Baseline (2026-06-02)

- 300 tests across 25 files, all passing.
- `uvx ruff check .` clean.

## How to apply

Always use `uv run --extra test pytest` for tests and `uvx ruff` for linting. Never use bare `pytest`, `python3.11`, or `uv run ruff`.
