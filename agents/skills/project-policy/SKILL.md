---
name: project-policy
description: Enforces project-local conventions for the TCF Bot Python Telegram bot. Use before writing, editing, or generating code in tcbot/, including handlers, database helpers, workflows, imports, utilities, tests, and configuration-related changes.
---

# TCF Bot Project Policy

Last updated: 2026-05-29

Use this skill before changing TCF Bot code. Keep changes focused, safe, and consistent with the
existing architecture. Prefer existing helpers and patterns over new abstractions.

## Mandatory Read-Before-Work and Update-After-Work

Before invoking this skill, you must already have read [`agents/CLAUDE.md`](../../CLAUDE.md), [`agents/RULES.md`](../../RULES.md), [`AGENTS.md`](../../../AGENTS.md), [`PLAN.md`](../../../PLAN.md), and [`CHANGELOG.md`](../../../CHANGELOG.md) at the start of this conversation. The full read/update tables live at [`agents/CLAUDE.md`](../../CLAUDE.md#mandatory-read-these-files-before-any-work).

After any code change in `tcbot/`, in the same turn:

- Add an entry to [`CHANGELOG.md`](../../../CHANGELOG.md) under `[Unreleased]`.
- Update [`PLAN.md`](../../../PLAN.md) when the change affects runtime, project state, priorities, or test counts.
- Update the matching `docs/<area>/<area>.md` and `docs/<feature>-detailed.md` if the area or feature changed.
- Update the matching `tests/test_*.py` if behavior changed.

Skipping the doc sweep is a defect of the same severity as a failing test.

## Project Snapshot

- Project: TCF Bot, a Telegram moderation and federation management bot.
- Runtime: Python 3.12.
- Telegram framework: `python-telegram-bot[job-queue] == 22.5`.
- Database: MongoDB through async Motor helpers.
- Keepalive: Flask health/keep-alive server.
- Tooling: `uv` for dependency management, Ruff for format/lint, pytest + pytest-asyncio for
  offline tests.
- Entry point: `python -m tcbot` on Windows, `python3 -m tcbot` elsewhere.

## Repository Boundaries

- Bot package: `tcbot/`.
- Command/event modules: `tcbot/modules/`.
- Shared module helpers: `tcbot/modules/helper/`.
- Conversation workflows: `tcbot/modules/helper/workflows/`.
- Database helpers: `tcbot/database/`.
- Runtime utilities: `tcbot/utils/`.
- Offline tests: `tests/`.

Do not place Telegram handlers, MongoDB access, workflows, or utility functions outside their
owning area.

## Python and Style Rules

- Put `from __future__ import annotations` as the first non-comment line in Python modules.
- Use Python 3.12 syntax and built-in generics: `list[str]`, `dict[str, int]`, `int | None`.
- Use 4-space indentation and keep diffs minimal.
- Avoid wildcard imports and inline imports.
- Use `logging.getLogger(__name__)`; do not use `print()`.
- Let Ruff handle formatting and import cleanup.
- Add comments only for non-obvious intent, constraints, or tradeoffs.

## Module and Handler Rules

- Top-level command modules belong in `tcbot/modules/*.py`.
- Modules should expose `__module_name__`, `__help_text__`, and `__handlers__` where consistent
  with existing modules.
- Async command handlers should be named `cmd_*`.
- Event handlers should be named `on_*`.
- Use existing decorators from `tcbot.modules.helper.decorators` for rate limiting, role checks,
  and execution logging where applicable.
- Register commands with existing prefix/filter helpers, especially `build_prefixed_filters()`.
- Message-event handlers may be exempt from command rate limiters when existing patterns do so.
- Do not duplicate command parsing, target extraction, keyboard, formatting, or role-check logic;
  reuse helpers under `tcbot/modules/helper/`.

## Conversation Workflow Rules

- Conversation handlers live only in `tcbot/modules/helper/workflows/`.
- Workflow files must be named `*_flow.py`; do not create `*_conv.py` files.
- Conversation states are module-level `WAITING_*` constants.
- Every conversation should provide a cancel path/fallback.
- Use configured timeout values from `cfg`, such as proof and appeal timeouts; avoid hardcoded
  timeout literals.
- Reuse existing flows when possible, such as moderation action, ban proof, and appeal flows.

## Database Rules

- Database access belongs in `tcbot/database/`, one domain/collection helper per `*_db.py` file.
- Handler modules must not call Mongo collections directly; use database helper functions.
- Keep database helpers async and fully typed.
- Prefer naming helpers `get_*`, `get_all_*`, `add_*`, `update_*`, `delete_*`, or an existing
  domain-specific pattern.
- Keep MongoDB schema changes backward-compatible unless a migration plan is included.
- When adding a collection or index-sensitive query, update index creation logic accordingly.
- Tests for database helpers must remain offline and mock external services.

## Telegram Message Rules

- Bot messages must use `parse_mode="HTML"`; do not introduce Markdown parse mode.
- Escape user-provided text with formatter helpers before interpolation.
- Prefer helpers from `tcbot/modules/helper/formatter.py`, such as `esc`, `code`, `mention`, and
  `bold`.
- Keep user-facing tone professional-friendly, concise, and clear.
- Always answer callback queries with `await query.answer()` before doing further callback work.
- Do not store `Update`, `Message`, or callback query objects beyond the handler lifetime.

## Role and Moderation Rules

- Use canonical role helpers from `tcbot.database.users_db`; do not chain manual owner/admin role
  checks.
- Use the shared permission helper `tcbot.modules.helper.decorators.resolve_and_check` for combined executor/target
  checks where appropriate.
- Ban and kick flows must auto-demote targets who currently hold a federation role before the
  destructive action proceeds.
- Preserve founder/admin/developer/tester hierarchy behavior and existing role labels.
- Never weaken authorization checks while refactoring.

## Async and Fan-Out Rules

- Keep Telegram and MongoDB I/O non-blocking.
- Use `asyncio.gather()` only when operations are independent and error handling remains clear.
- Multi-group Telegram actions must use `tcbot.utils.dispatch.fan_out()` to bound concurrency and
  collect per-group results.
- When iterating over Telegram API calls manually, handle recoverable exceptions and log useful
  context.

## Datetime Rules

- Use helpers from `tcbot.utils.timedate_format` for UTC timestamps, normalization, and display.
- Use project helpers such as `utc_now()`, `to_utc()`, `fmt_dt()`, and `utc_now_str()` as
  appropriate.
- Do not introduce raw `datetime.utcnow()` or ad-hoc timezone formatting.

## Secrets and Configuration

- Never hardcode or commit bot tokens, MongoDB URIs, API keys, passwords, or private secrets.
- Read secrets from environment/config mechanisms already used by the project.
- Do not edit `config.env` during normal code changes.
- Keep `config.env.example` as a template only when configuration documentation genuinely changes.
- Do not log secrets or include them in errors, tests, fixtures, or examples.

## Dependencies and Tooling

- Use `uv` for dependency changes; do not hand-edit lockfiles casually.
- Prefer dependencies already present in `pyproject.toml`.
- Add new packages only when the project cannot reasonably solve the task with existing code.
- If dependencies change, update both `pyproject.toml` and `uv.lock` through the proper `uv`
  workflow.

## Testing and Validation

Choose the narrowest useful validation first, then broaden when appropriate.

- Source changes: run relevant pytest tests, then consider `uv run --extra test pytest tests/ -v`.
- Formatting/lint changes: run `uv run ruff format .` and `uv run ruff check --fix .` when safe.
- Documentation or skill-only changes: tests are usually unnecessary; state that no runtime
  validation was run.
- New or changed helpers, workflows, decorators, database functions, or formatting behavior should
  include or update offline tests.
- Do not claim validation passed unless the command was run and succeeded.

## Pre-Edit Checklist

Before editing TCF Bot code, verify:

- The change belongs in the selected file and not in an existing helper or workflow.
- Handlers stay in `tcbot/modules/`; workflows stay in `*_flow.py`; database access stays in
  `tcbot/database/`.
- Messages are HTML-only and user content is escaped.
- Role checks use canonical helpers and destructive actions preserve auto-demotion behavior.
- Multi-group actions use `fan_out()`.
- Datetimes use project datetime helpers.
- No secrets, credentials, or private IDs are introduced.
- Validation plan is appropriate for the scope of the change.
