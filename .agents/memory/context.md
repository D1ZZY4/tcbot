---
name: Project context
description: Current state of TCF Bot project — what is done, in progress, and pending. Update before every commit.
---

# TCF Bot — Current Context

**Last updated:** 2026-06-02

## What is done

- Python 3.12, uv, python-telegram-bot 22.5, Motor/MongoDB stack fully configured on Replit.
- BOT_TOKEN and MONGODB_URI in Replit Secrets; PORT=8080 in environment.
- 332 tests across 26 test files; full suite passes offline.
- `uv run ruff format .` and `uv run ruff check .` both clean across 98 source files.
- All P1/P2/P3 backlog items resolved (ConversationHandler tests, pagination NameError, composite indexes, async.gather conversions, shared replies.py, em-dash removal, cache TTL constants, keyboards.py dead code).
- `docs/mapping.md` updated: added `identity.py`, `replies.py` to helper section; added `pagination.py` to utils section.
- `maintenance.py` hardcoded `timeout=3.0` extracted to named constant `_MEMBERSHIP_CHECK_TIMEOUT`.
- Comprehensive source audit: CLEAN — no emoji, em-dash, or emoticons anywhere in tcbot/.
- Bot restarts cleanly: MongoDB connected, indexes ensured, 75 handlers registered, polling active.

## What is in progress

Nothing. All known items resolved.

## What is pending (optional)

- Module-interface types in tcbot/modules/types.py (only if signatures grow ambiguous).
- Query metrics collection (data-driven; gather Atlas PA data first).

## Known runtime notes

- `python -m ruff check .` and `python -m ruff format .` are the correct lint/format commands on Replit (packages installed via pip; uv sync fails on nix store).
- `python -m pytest tests/ -q` is the correct test command on Replit.
- Workflows are configured to use `python -m tcbot` and `python -m pytest tests/ -v` (no `uv run`).
- Flask keep-alive runs on PORT=8080 (mapped by Replit to external port 80).
- Bot fails fast when BOT_TOKEN/MONGODB_URI/OWNER_ID are not set. Secrets must be in Replit Secrets.

## Blockers

None.
