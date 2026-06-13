---
name: Project context
description: Current state of TCF Bot project - what is done, in progress, and pending. Update before every commit.
---

# TCF Bot - Current Context

**Last updated:** 2026-06-13 (session 90 wave 1)

## What is done

- Session 89 wave 2 (2026-06-13): Final typographic character cleanup + comprehensive final audit.
  - Bug #216: admins.py Role Hierarchy help text used `›` (U+203A) as visual separator. Replaced with `>` (ASCII).
  - Bug #217: help.py section header template used `\u203a` as separator. Replaced with HTML entity `&gt;`.
  - SKILL.md: Removed 4 em-dashes from `.agents/skills/context7-mcp/SKILL.md` (table N/A cells + parentheses).
  - AST gather audit: Full scan of all 72 tcbot/ Python files. 0 real gather bugs (dispatch.py hit is false positive: `_slot()` catches all exceptions internally).
  - Unicode audit: Full regex scan across tcbot/, docs/, .agents/. 0 emoji/em-dash/en-dash/U+203A anywhere.
  - Ruff: 72 files formatted + all checks passed.

- Session 89 wave 1 (2026-06-13): Identity.py refusal table gaps + disconnecting.py gather result-checking. Bugs #212-215.
- Session 88 waves 1-2 (2026-06-13): Bugs #202-211 fixed.
- Session 87 waves 1-6 (2026-06-13): Bugs #187-201 fixed.
- Session 86 (2026-06-12): Bugs #179a-186 fixed.
- Sessions 65-85 (2026-06-02 to 2026-06-12): Comprehensive v4.1.1 development and hardening.

- Session 90 wave 1 (2026-06-13): Housekeeping + CI gate.
  - Bug #218: Created `.dockerignore` (missing — entire repo was in Docker build context).
  - Bug #219: Created `.github/workflows/lint.yml` (blocking CI gate: ruff format --check, ruff check, import tcbot).
  - Bug #220: Removed `RUF001` from `pyproject.toml` ruff ignore (U+203A fully gone since s89w2; stale ignore would hide future regressions).
  - Docs: Updated `docs/workflows-guide.md` (4→5 workflows, added Lint section with proper numbering, updated Workflow Dependencies diagram).
  - Docs: Updated `README.md` CI/CD section (4→5 workflows, added Lint subsection).
  - CHANGELOG.md: Updated with all Bug #218-220 entries.

## AUDIT STATUS

**FULLY DRY** as of session 90 wave 1. Multiple waves across all 72 tcbot/ files found 0 new real bugs.
Total bugs fixed: #1-#220. All `asyncio.gather` calls verified via AST scan. All unicode clean via regex scan.
GitHub workflows, Docker, docs: all audited and clean.
No remaining known bugs. warns_db.py atomicity is a design-level note, not a crash bug.

## Runtime info

- Bot running: MongoDB, Redis hiredis 3.4.0, APScheduler CBORSerializer, 27/27 indexes, polling active.
- File count: 72 Python files.
- Ruff: All checks passed (0 errors, 72 files clean). RUF001 ignore removed (0 U+203A in any Python file).
