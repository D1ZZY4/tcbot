---
name: Technical decisions
description: Non-trivial technical decisions made during development. Format: date + decision + why.
---

# TCF Bot — Technical Decisions

## 2026-06-02: Pagination helpers centralized in tcbot.utils.pagination

**Decision:** `paginate`, `nav_row`, and `date_or_unknown` live exclusively in `tcbot.utils.pagination`. Flow files (`stats_flow.py`, `check_flow.py`) import and call them directly; they do not define private wrapper functions.

**Why:** An earlier refactor extracted these into the utils module but left the old private-name call sites (`_paginate`, `_nav_row`, `_date`) in both flow files. These undefined names caused `NameError` at runtime when any stats or check drill-down was triggered. Centralizing ensures a single implementation, single test surface, and prevents re-introduction of stale wrappers.

**How to apply:** Any new `*_flow.py` that paginates must `from tcbot.utils.pagination import date_or_unknown, nav_row, paginate` and call `paginate(items, page, _PAGE_SIZE)`.

---

## 2026-06-02: Test command on Replit is `uv run --extra test pytest`; ruff is `uvx ruff`

**Decision:** On the Replit environment, `uv run ruff` fails (no such file). The correct commands are `uvx ruff format .`, `uvx ruff check --fix .`, and `uv run --extra test pytest tests/ -q`.

**Why:** Ruff is a dev-extra dependency. `uv run ruff` only works when ruff is in the runtime dependencies or in the PATH. On Replit, `uvx` resolves and runs dev tools correctly. The docs in `.agents/` say `uv run ruff` — that is wrong for this environment. Use `uvx ruff` instead.

**How to apply:** Always run `uvx ruff check .` and `uvx ruff format .` for lint/format checks; `uv run --extra test pytest` for tests.

---

## 2026-06-02: `asyncio_mode = "auto"` in pytest config

**Decision:** All async test functions use `async def` directly without `@pytest.mark.asyncio`. This is enabled by `asyncio_mode = "auto"` in `pyproject.toml` `[tool.pytest.ini_options]`.

**Why:** Reduces boilerplate across the 300+ test suite. Consistent with the existing test file patterns already in the repo.

**How to apply:** Write async tests as `async def test_*(...):` without any `asyncio` mark decorator.

---

## 2026-06-02: Memory files live in `.agents/memory/`, MEMORY.md is the index

**Decision:** Persistent cross-session memory uses `.agents/memory/MEMORY.md` as a one-line-per-entry index pointing to topic files in the same directory. Context, progress, and decisions each have their own file.

**Why:** The Replit platform memory can be reset on account change. Storing state in tracked files guarantees continuity across sessions and accounts.

**How to apply:** Before finishing any work session, update context.md (state), progress.md (item status), and decisions.md (new decisions). Update MEMORY.md index if a new topic file is created.
