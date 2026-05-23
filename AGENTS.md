# Repository Guidelines

## Project Structure & Module Organization
Core code lives in `tcbot/`: command modules in `tcbot/modules/`, shared helpers in `tcbot/modules/helper/`, MongoDB access in `tcbot/database/`, and runtime utilities in `tcbot/utils/`. Tests are in `tests/` and run fully offline. Project notes and agent-specific rules live in `agents/` and `docs/`. Keep new database code in a `*_db.py` file and new conversation flows in a `*_flow.py` file.

## Build, Test, and Development Commands
- `uv sync` installs Python 3.12 dependencies from `pyproject.toml` and `uv.lock`.
- `python3 -m tcbot` starts the bot locally.
- `python3 -m pytest tests/ -v` runs the full test suite.
- `uv run ruff format .` reformats Python files with Ruff.
- `uv run ruff check --fix .` applies lint fixes and import cleanup.
- `docker-compose up --build` starts the bot plus a local MongoDB instance.

## Coding Style & Naming Conventions
Use Python 3.12, 4-space indentation, and `from __future__ import annotations` as the first non-comment line in every module. Ruff is the repo formatter and linter, so prefer `ruff format` for whitespace/layout and `ruff check --fix` for automatic cleanup. Prefer built-in generic types such as `list[str]` and `dict[str, int]`; avoid inline imports. Name async handlers `cmd_*` or `on_*`, conversation states `WAITING_*`, and keep module files descriptive (`banning.py`, `appeal_flow.py`). Follow the existing HTML-only bot message style and the conventions in `agents/STYLE-CODE.md`.

## Testing Guidelines
The project uses `pytest` with `pytest-asyncio`. Test files are named `test_*.py` and live under `tests/`. Prefer small, behavior-focused tests that mirror the existing offline coverage. If you change database behavior, handlers, or shared helpers, add or update tests in the matching file.

## Commit & Pull Request Guidelines
Git history uses conventional commits: `feat:`, `fix:`, `refactor:`, `docs:`, `test:`, and `chore:`. Keep commits focused and descriptive. Pull requests should summarize the change, note any config or database impact, and include test results. Add screenshots or log excerpts only for user-visible behavior changes.

## Security & Configuration Tips
Do not commit real secrets. Use `config.env` locally and Replit Secrets in hosted environments. Required values include `BOT_TOKEN` and `MONGODB_URI`. For schema changes, update all read paths and migration-sensitive code together so existing MongoDB data remains compatible.
