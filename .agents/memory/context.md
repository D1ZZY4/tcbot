---
name: Project context
description: Current state of TCF Bot project — what is done, in progress, and pending. Update before every commit.
---

# TCF Bot — Current Context

**Last updated:** 2026-06-02

## What is done

- Python 3.12, uv, python-telegram-bot 22.5, Motor/MongoDB stack fully configured on Replit.
- BOT_TOKEN and MONGODB_URI in Replit Secrets; PORT=8080 in environment.
- 319 tests across 26 test files; full suite passes offline.
- `uv run ruff format .` and `uv run ruff check .` both clean across all 97 source files.
- P1 backlog fully resolved (ConversationHandler state-machine tests, stats_flow pagination NameError, check_flow pagination NameError).
- P2 backlog fully resolved (docstrings on flow class methods, workflow docs).
- `test_check_flow.py` added: 19 tests covering Check.profile, bans_list, ban_detail, warns_by_group, warns_in_group, kicks_list, mutes_list, appeals_list.
- Memory files created and maintained: context.md, progress.md, decisions.md, structure.md.
- `pyproject.toml`: ruff moved to `[dependency-groups] dev = ["ruff"]` so `uv run ruff` works.
- `PLAN.md` P3.1 resolved: `uv run ruff` now works correctly.
- `PLAN.md` P3.3 resolved: `{user_id, first_name, username}` composite index added to `mongos.ensure_indexes()`.
- `PLAN.md` P5.1 resolved: batch `$in` queries now covered by composite index.
- `README.md` test count updated: 319 tests / 26 files.
- `.agents/skills/python-code-quality/SKILL.md`: pyproject.toml snippet updated to current structure.
- `docs/databases/databases.md` index table: composite index row added.
- Full 7-step verification: sync, pip install, import, startup, lint, tests (319), smoke (75 handlers). All green.
- Bot restarts cleanly: MongoDB connected, indexes ensured, 75 handlers registered, polling active.

## What is in progress

Working on broader improvements: named cache TTL constants, BOT_TOKEN/MONGODB_URI format validation,
dead-code audit, rate-limiter constant extraction.

## What is pending (P3 optional hardening + broader improvements)

- BOT_TOKEN format validation (optional; PTB fails fast anyway; quick to add).
- MONGODB_URI format validation (optional; driver fails fast; quick to add).
- cache.py TTL values as named constants (currently inline floats).
- Rate-limiter period/limit constants in module files.
- Broader dead-code and duplicate-code audit.
- Module-interface types in tcbot/modules/types.py (only if signatures grow ambiguous).

## Known runtime notes

- `uv run ruff check .` and `uv run ruff format .` are the correct lint/format commands.
- `uv run --extra test pytest tests/ -q` is the correct test command.
- `uv run python -c "from tcbot.modules import get_handlers; h = get_handlers(); print(f'smoke OK: {len(h)} handlers')"` is the correct smoke test.
- Flask keep-alive runs on PORT=8080 (mapped by Replit to external port 80).
- Bot starts on `uv run python -m tcbot`.

## Blockers

None.
