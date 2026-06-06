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

## 2026-06-02: `uv run ruff` is the correct command; `uvx ruff` is not needed

**Decision:** On this Replit environment, `uv run ruff` is the correct way to run ruff. Ruff belongs in `[dependency-groups] dev = ["ruff"]` in `pyproject.toml` so `uv sync` installs it into the project venv and `uv run ruff` resolves it correctly.

**Why:** An earlier session mistakenly recorded `uvx ruff` as the correct command because ruff was in `[project.optional-dependencies.dev]`, which `uv run` does not install by default. Moving ruff to `[dependency-groups]` (PEP 735) makes `uv sync` install it automatically. `uv run ruff check .` and `uv run ruff format .` now work without any extra flags.

**How to apply:** Always run `uv run ruff check .` and `uv run ruff format .`. Never use `uvx ruff`. `uv run --extra test pytest` is still the correct test command.

---

## 2026-06-02: `asyncio_mode = "auto"` in pytest config

**Decision:** All async test functions use `async def` directly without `@pytest.mark.asyncio`. This is enabled by `asyncio_mode = "auto"` in `pyproject.toml` `[tool.pytest.ini_options]`.

**Why:** Reduces boilerplate across the 300+ test suite. Consistent with the existing test file patterns already in the repo.

**How to apply:** Write async tests as `async def test_*(...):` without any `asyncio` mark decorator.

---

## 2026-06-06: Frozen dataclass objects must be patched at module level

**Decision:** When a module-level object is a frozen dataclass (e.g. `connection` in `tcbot.modules.connecting`), its attributes cannot be patched via `patch("module.obj.attr", ...)` because frozen dataclass instances raise `FrozenInstanceError` on attribute assignment. Instead, replace the entire object at the module level.

**Why:** `patch("tcbot.modules.connecting.connection.check_perms", ...)` tries to `setattr(connection, "check_perms", mock)` which raises `dataclasses.FrozenInstanceError`. The cleanup in `__exit__` then also fails (`cannot delete field`), causing the `patch` context manager to raise.

**How to apply:** In tests, use `monkeypatch.setattr(module, "connection", MagicMock(...))` to replace the entire frozen-dataclass instance with a plain `MagicMock` whose methods can be freely configured. Applies to any frozen-dataclass singleton that is imported as a module-level name.

---

## 2026-06-02: Memory files live in `.agents/memory/`, MEMORY.md is the index

**Decision:** Persistent cross-session memory uses `.agents/memory/MEMORY.md` as a one-line-per-entry index pointing to topic files in the same directory. Context, progress, and decisions each have their own file.

**Why:** The Replit platform memory can be reset on account change. Storing state in tracked files guarantees continuity across sessions and accounts.

**How to apply:** Before finishing any work session, update context.md (state), progress.md (last-known work), and decisions.md (new decisions). Update MEMORY.md index if a new topic file is created.
