---
name: Project context
description: Current state of TCF Bot project - what is done, in progress, and pending. Update before every commit.
---

# TCF Bot - Current Context

**Last updated:** 2026-06-13 (session 92)

## What is done

- Session 92 (2026-06-13): Confirmation-only scan (no new bugs). Read 35+ files: bans_db.py, users_roles.py (full), ban_flow.py (full 437 lines), connected_flow.py, appeal_flow.py, cache.py (full 324 lines), keyboards.py (full 319 lines), mongos.py (full 181 lines). All clean. Ruff: 73 files formatted + all checks passed. `import tcbot` OK. FULLY DRY status reconfirmed.

- Session 91 (2026-06-13): Added `netspeed.py` module + Bug #231 decorator-order fix.
  - Feature: `tcbot/modules/netspeed.py` -- `/ping` (alias `/p`) and `/speedtest` (alias `/st`), Founder-only, rate-limited 3/60s. `/ping` measures Telegram API round-trip. `/speedtest` runs `speedtest-cli` in thread executor (non-blocking). Both use `build_prefixed_filters` and export `__handlers__`. `speedtest-cli==2.1.3` added to `pyproject.toml`.
  - Bug #231: Decorator order was wrong in both handlers (`@owner_only` outermost, `@ratelimiter` second). Fixed to: `@ratelimiter` outermost, `@owner_only` second, `@log_execution` innermost, per `RULES.md`.
  - Updated: `CHANGELOG.md`, `docs/modules/modules.md`, `structure.md`, `context.md`, `progress.md`.
  - Ruff: All checks passed. Import check passed.

- Session 89 wave 2 (2026-06-13): Final typographic character cleanup + comprehensive final audit.
  - Bug #216: admins.py Role Hierarchy help text used `>` (U+203A) as visual separator. Replaced with `>` (ASCII).
  - Bug #217: help.py section header template used `\u203a` as separator. Replaced with HTML entity `&gt;`.
  - SKILL.md: Removed 4 em-dashes from `.agents/skills/context7-mcp/SKILL.md`.
  - AST gather audit: Full scan of all 72 tcbot/ Python files. 0 real gather bugs.
  - Unicode audit: Full regex scan across tcbot/, docs/, .agents/. 0 emoji/em-dash/en-dash/U+203A anywhere.
  - Ruff: 72 files formatted + all checks passed.

- Session 89 wave 1 (2026-06-13): Identity.py refusal table gaps + disconnecting.py gather result-checking. Bugs #212-215.
- Session 88 waves 1-2 (2026-06-13): Bugs #202-211 fixed.
- Session 87 waves 1-6 (2026-06-13): Bugs #187-201 fixed.
- Session 86 (2026-06-12): Bugs #179a-186 fixed.
- Sessions 65-85 (2026-06-02 to 2026-06-12): Comprehensive v4.1.1 development and hardening.

- Session 90 wave 2 (2026-06-13): Bugs #221-230 (shutdown gather, 9x q.answer before parse, 3x admins parse).
- Session 90 wave 1 (2026-06-13): Housekeeping + CI gate.
  - Bug #218: Created `.dockerignore`.
  - Bug #219: Created `.github/workflows/lint.yml` (blocking CI gate).
  - Bug #220: Removed `RUF001` from ruff ignore.
  - Docs: Updated `docs/workflows-guide.md` and `README.md` CI/CD section.

## AUDIT STATUS

**FULLY DRY** as of session 91. All 73 tcbot/ Python files ruff-clean, import-check passing.
Total bugs fixed: #1-#231.

## Runtime info

- Bot running: MongoDB, Redis hiredis 3.4.0, APScheduler CBORSerializer, 27/27 indexes, polling active.
- File count: 73 Python files (72 original + netspeed.py).
- Ruff: All checks passed (0 errors, 73 files clean).

## Agent communication rule

ALWAYS respond to the user in Indonesian (Bahasa Indonesia profesional). All code, docstrings, comments, docs, CHANGELOG, commit messages, and `.agents/memory/` files remain in English.
