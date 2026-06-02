---
name: Project context
description: Current state of TCF Bot project — what is done, in progress, and pending. Update before every commit.
---

# TCF Bot — Current Context

**Last updated:** 2026-06-02 (session 5)

## What is done

- Python 3.12, uv, python-telegram-bot 22.5, Motor/MongoDB stack fully configured on Replit.
- BOT_TOKEN and MONGODB_URI in Replit Secrets; PORT=8080 in environment.
- 1078 tests across 69 test files; full suite passes offline with 0 warnings.
- `python -m ruff format .` and `python -m ruff check .` both clean (141 files formatted).
- All P1/P2/P3 backlog items resolved (ConversationHandler tests, pagination NameError, composite indexes, asyncio.gather conversions, shared replies.py, em-dash removal, cache TTL constants, keyboards.py dead code).
- `docs/mapping.md` updated: added `identity.py`, `replies.py` to helper section; added `pagination.py` to utils section.
- `maintenance.py` and `disconnecting.py` hardcoded `timeout=3.0` extracted to named constants.
- `maintenance.py` converted to `__help_text__` + `__help_sections__` format (last holdout; all modules now consistent).
- `replies.py` now has full permission-tier set: `PERM_TESTER_ABOVE`, `PERM_DEV_ABOVE`, `PERM_ADMIN_ABOVE`, `PERM_STAFF_ONLY`, `PERM_FOUNDER_ONLY`.
- `admins.py` and `broadcasting.py` updated to use `replies.PERM_FOUNDER_ONLY` / `replies.PERM_STAFF_ONLY` throughout.
- `start.py` welcome messages rewritten to fix broken grammar.
- Comprehensive source audit: CLEAN — no emoji, em-dash, or emoticons anywhere in tcbot/.
- Bot restarts cleanly: MongoDB connected, indexes ensured, 75 handlers registered, polling active.
- `kicking_flow.py` SyntaxError fixed: `_MSG_REJOIN_ALLOWED` was used as implicit string concatenation (only works with string literals); changed to `f"{_MSG_REJOIN_ALLOWED}"`.
- All inline-string extractions complete across all modules and workflows; no unextracted static user-facing reply strings remain.
- Comprehensive doc audit complete (2026-06-02): fixed 4 stale references — docs-maintainer SKILL.md test count (300/25 → 698/50), helper.md replies.py table (10 → 15 constants), utils.md mermaid diagram (logging_setup.py → logger.py), structure.md filename + test count.
- 15 new test files added (2026-06-02): kicks_db, mutes_db, queues_db, users_cache, groups_db, error_reporter, mongos, formatter, extraction, parse_editmsg, ban_info (+ 4 earlier utility files). Bug fix: `_esc()` in error_reporter.py hardened to accept `str | None`. Suite: 698 → 966 tests / 50 → 65 files.

- PTBDeprecationWarning (`retry_after` type change) eliminated: `PTB_TIMEDELTA=1` added to
  `tests/conftest.py` test env; belt-and-suspenders filterwarnings entry added to `pyproject.toml`.
- 8 test files reformatted by `ruff format` (style only).
- `tcbot/__main__.py`: module-level `warnings.filterwarnings` added to suppress intentional
  PTBUserWarning about `per_message=False` + ConversationHandler; startup log is now fully clean.
- Docstrings added to all 20 large public handler/executor functions that had none: 6 in
  `admins.py`, 2 in `disconnecting.py`, 2 in `warning_flow.py`, plus 1 each in `banning.py`,
  `broadcasting.py`, `checking.py`, `connecting.py`, `kicking.py`, `maintenance.py`, `muting.py`,
  `start.py`, `warnings.py`, `unban_flow.py`. AST audit now shows 0 missing docstrings on
  functions 30+ lines long.
- Comprehensive source audit (session 2): no emoji, no em-dash, no emoticons; all typing imports
  are appropriate built-in or stdlib; no blocking I/O; no hardcoded timeouts beyond named constants.

- 3 more test files added (session 3 continued): `test_alive.py` (5 tests),
  `test_documents.py` (17 tests), `test_types.py` (12 tests). Suite: 966 → 1039 / 65 → 69 files.
- Stale test counts (1005/66 → 1039/69) updated in PLAN.md (×2), README.md (×2),
  replit.md, AGENTS.md.
- Docstrings batch 1 (14 functions, 10+ lines), batch 2 (22 functions, 5-9 lines),
  batch 3 (13 functions, 3-4 lines): AST audit now reports 0 public functions of 3+ lines
  missing a docstring across the entire tcbot/ package.
- Class docstrings: 10 public TypedDict classes in documents.py now have docstrings.
  AST audit reports 0 public classes missing a docstring across the entire tcbot/ package.
- CHANGELOG.md updated with all session 3 work (3 test file entries + 3 docstring batch
  entries + class docstring entry).

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
