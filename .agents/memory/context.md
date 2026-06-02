---
name: Project context
description: Current state of TCF Bot project — what is done, in progress, and pending. Update before every commit.
---

# TCF Bot — Current Context

**Last updated:** 2026-06-02

## What is done

- Python 3.12, uv, python-telegram-bot 22.5, Motor/MongoDB stack fully configured on Replit.
- BOT_TOKEN and MONGODB_URI in Replit Secrets; PORT=8080 in environment.
- 300+ tests across 25+ test files; full suite passes offline.
- ruff format and ruff check clean across all 96+ source files.
- P1 backlog fully resolved (ConversationHandler state-machine tests, stats_flow pagination NameError, check_flow pagination NameError).
- P2 backlog fully resolved (docstrings on flow class methods, workflow docs).
- `test_check_flow.py` added: 18 tests covering Check.profile, bans_list, ban_detail, warns_by_group, warns_in_group, kicks_list, mutes_list, appeals_list.
- Memory files created: context.md, progress.md, decisions.md, structure.md.

## What is in progress

Nothing currently blocked or in flight.

## What is pending (P3 optional hardening)

- BOT_TOKEN format validation (optional; PTB fails fast anyway).
- MONGODB_URI format validation (optional; driver fails fast).
- Covered-query composite index on member_cache (marginal perf gain).
- Shared module-interface types in tcbot/modules/types.py (only if signatures grow ambiguous).

## Known runtime notes

- `uv run ruff` does NOT work on Replit; use `uvx ruff check .` and `uvx ruff format .`.
- `uv run --extra test pytest tests/ -q` is the correct test command.
- Flask keep-alive runs on PORT=8080 (mapped by Replit to external port 80).
- Bot starts on `uv run python -m tcbot`.

## Blockers

None.
