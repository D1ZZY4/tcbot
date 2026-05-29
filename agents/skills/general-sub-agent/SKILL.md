---
name: general-sub-agent
description: Provides a general-purpose TCF Bot workflow for broad coding tasks, including codebase inspection, safe implementation, validation, and concise summaries.
---
Last updated: 2026-05-28


# General Sub Agent

Before invoking this skill, confirm the read/update rules in [`agents/CLAUDE.md`](../../CLAUDE.md#mandatory-read-these-files-before-any-work). After any change, update [`CHANGELOG.md`](../../../CHANGELOG.md) and any related `docs/*.md` in the same turn.

Use this project-local skill when the user asks for broad help that is not covered by a more specific TCF Bot skill. It is useful for general exploration, code review, small bug fixes, documentation updates, and focused quality improvements across the repository.

This skill was copied from the user's global `general-sub-agent` skill and adapted for the TCF Bot project.

## Project Context

TCF Bot is a Python 3.12 Telegram moderation bot built with:

- `python-telegram-bot[job-queue] == 22.5`
- Motor/MongoDB for persistence
- Flask for the keep-alive health endpoint
- `uv` for dependency management
- Ruff for formatting and linting
- pytest + pytest-asyncio for offline tests

Main source code lives in `tcbot/`, offline tests live in `tests/`, developer docs live in `docs/`, and agent/contributor rules live in `agents/`.

## When To Use

Use this skill when the task is broad, mixed, or exploratory, for example:

- "Explore this codebase and improve obvious issues."
- "Review the recent changes."
- "Fix small bugs and improve code quality."
- "Update docs and make sure they match the current implementation."
- "Investigate why something is failing."

Prefer a more specific local skill when available:

- Use `project-policy` before editing TCBot source code.
- Use `telegram-bot-builder` for PTB handlers and Telegram UX.
- Use `async-python-patterns` for async handlers, cancellation, fan-out, and pytest-asyncio tests.
- Use `mongodb-query-optimizer` for database query/index performance.
- Use `python-code-quality` for Ruff, pytest, typing, and quality gates.
- Use `mermaid-diagrams` for diagrams.

## Workflow

1. Inspect relevant files, symbols, tests, and configuration before making changes.
2. Check `git status` and avoid overwriting user work.
3. Form a small plan that targets the root cause instead of symptoms.
4. Make minimal, focused edits consistent with the surrounding style.
5. Update directly related tests or docs when behavior changes.
6. Validate with the most specific command first, then broader checks when practical.
7. Summarize changed files, validation results, and any remaining risks.

## Implementation Rules

- Keep changes surgical in existing code.
- Do not introduce dependencies unless the task clearly requires them.
- Do not touch `config.env` unless the user explicitly asks; never print secrets.
- Do not rewrite large files just to make them prettier.
- Respect project ownership boundaries:
  - command handlers: `tcbot/modules/`
  - shared helpers: `tcbot/modules/helper/`
  - workflows: `tcbot/modules/helper/workflows/*_flow.py`
  - database helpers: `tcbot/database/*_db.py`
  - utilities: `tcbot/utils/`
  - tests: `tests/`
- Keep bot messages HTML-only and escape user-controlled text with formatter helpers.
- Use `tcbot.utils.dispatch.fan_out()` for multi-group Telegram API fan-out.
- Use `tcbot.utils.timedate_format` helpers for UTC time.

## Validation Guide

Choose commands based on the scope:

```bash
uv run ruff check .
uv run ruff format .
uv run --extra test pytest tests/ -q
uv run --extra test pytest --collect-only -q
python -m tcbot
```

Notes:

- On Windows, `python` may be available when `python3` is not.
- Long-running bot startup should be run with a timeout during agent validation.
- If `uv sync` is run without `--extra test`, pytest dependencies may be removed from the environment.

## Communication Style

Be concise, direct, and friendly. Explain what changed in plain English, mention validation honestly, and call out uncertainty or follow-up work without over-explaining.

## Output Checklist

Before finishing, include:

- a short summary of what changed,
- project-relative file paths,
- validation commands and results,
- any skipped validation and why,
- any user-owned files that were intentionally not touched.
