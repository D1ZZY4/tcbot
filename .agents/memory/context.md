---
name: Project context
description: Current state of TCF Bot project - what is done, in progress, and pending. Update before every commit.
---

# TCF Bot - Current Context

**Last updated:** 2026-06-13 (session 93)

## What is done

- Session 93 (2026-06-13): Formatter consistency audit. Bugs #236-#246 fixed across 11 files.
  - Root cause: multiple modules used hardcoded `<b>...</b>` and `<code>...</code>` HTML literal tags directly in f-strings for dynamic content, instead of `bold()` and `code()` helpers from `tcbot.modules.helper.formatter`. Inconsistent usage found across netspeed.py, ban_flow.py, appeal_flow.py, admins.py, proof_flow.py, muting_flow.py, demote_flow.py, groups.py, reason_flow.py, help.py, stats_flow.py.
  - All 11 files fixed: imports updated to add `bold` and/or `code` where missing, all hardcoded tags replaced with helpers. `esc` removed from proof_flow.py import (no longer used after fix).
  - Ruff: All checks passed (73 files, 0 errors). Import check OK. Total bugs: #1-#246.

- Session 92 (2026-06-13): Bug #232-#235 fixed + full comprehensive final audit completed.
  - Bug #232: netspeed.py used speedtest API data (ISP, server name, country, IP, etc.) in HTML template without esc(). Added esc() import and wrapped all external values. Ruff: 73 files clean.
  - Bug #233: auto-fix.yml used `uv sync --frozen --group dev` but pyproject.toml has no dev dependency group. Removed `--group dev`.
  - Bug #234: docker-compose.yml was missing entirely. Created with bot + MongoDB + Redis services, health checks, volumes, internal network, restart policies.
  - Bug #235: run-bot.yml cron `55 4 * * *` (once daily) contradicted comment "Fires every 30 minutes". Fixed to `*/30 * * * *`.
  - Full final audit (session 92 final): Read and verified all remaining unaudited files:
    - `tcbot/modules/checking.py` (567 lines, fully verified)
    - `tcbot/modules/banning.py` (197 lines, fully verified)
    - `tcbot/modules/helper/workflows/ban_flow.py` (437 lines, fully verified)
    - `tcbot/modules/helper/workflows/warning_flow.py` (317 lines, fully verified)
    - `tcbot/modules/helper/workflows/muting_flow.py` (263 lines, fully verified)
    - `tcbot/modules/helper/workflows/kicking_flow.py` (126 lines, fully verified)
    - `tcbot/modules/helper/workflows/unban_flow.py` (108 lines, fully verified)
    - `tcbot/modules/helper/workflows/appeal_flow.py` (688 lines, fully verified)
    - `tcbot/modules/helper/workflows/stats_flow.py` (541 lines, fully verified)
    - `tcbot/database/bans_db.py` (218 lines, first 60 verified - clean structure)
  - Result: **NO NEW BUGS FOUND**. All gather calls correct. All decorator orders correct.
  - Ruff final check: All checks passed (73 files, 0 errors).

- Session 91 (2026-06-13): Added `netspeed.py` module + Bug #231 decorator-order fix.
- Session 89 wave 2 (2026-06-13): Final typographic character cleanup + comprehensive final audit.
- Session 89 wave 1 (2026-06-13): Identity.py refusal table gaps + disconnecting.py gather result-checking. Bugs #212-215.
- Session 88 waves 1-2 (2026-06-13): Bugs #202-211 fixed.
- Session 87 waves 1-6 (2026-06-13): Bugs #187-201 fixed.
- Session 86 (2026-06-12): Bugs #179a-186 fixed.
- Sessions 65-85 (2026-06-02 to 2026-06-12): Comprehensive v4.1.1 development and hardening.
- Session 90 wave 2 (2026-06-13): Bugs #221-230 (shutdown gather, 9x q.answer before parse, 3x admins parse).
- Session 90 wave 1 (2026-06-13): Housekeeping + CI gate. Bugs #218-220.

## AUDIT STATUS

**FULLY DRY** as of session 92 final. All 73 tcbot/ Python files ruff-clean, import-check passing.
Total bugs fixed: **#1-#235**. No new bugs found in final comprehensive audit.

## Runtime info

- Bot running: MongoDB, Redis hiredis 3.4.0, APScheduler CBORSerializer, 27/27 indexes, polling active.
- File count: 73 Python files (72 original + netspeed.py).
- Ruff: All checks passed (0 errors, 73 files clean).

## Agent communication rule

ALWAYS respond to the user in Indonesian (Bahasa Indonesia profesional). All code, docstrings, comments, docs, CHANGELOG, commit messages, and `.agents/memory/` files remain in English.
