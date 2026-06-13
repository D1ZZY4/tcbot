---
name: Progress tracker
description: Item-by-item status of the improvement plan. Updated at each commit checkpoint.
---

# TCF Bot - Progress

**Last updated:** 2026-06-13 (session 95)

## Verification baseline

| Check | Result |
|---|---|
| `uv sync` | PASS |
| `uv pip install -e .` | PASS |
| `uv run python -c "import tcbot; print('import OK')"` | PASS (re-verified session 93) |
| `uv run python -m tcbot` | PASS by runtime evidence: MongoDB connected, indexes ensured, scheduler started, bot polling active |
| `uv run ruff format .` | PASS (73 files) |
| `uv run ruff check .` | PASS (All checks passed, verified session 95) |
| asyncio task-GC fix isolated test (session 43) | PASS: task registered on schedule, discarded on completion, report coroutine ran |
| annotation AST audit | PASS: 0 non-dunder function parameters missing type annotations |
| docs audit (session 74) | PASS: mapping.md top-level layout completed; 3 new Mermaid diagrams added; all code files audited clean |
| Final comprehensive audit (session 92 final) | PASS: All remaining workflow, module, database files verified. 0 new bugs found. |
| Formatter consistency audit (session 93) | PASS: 11 files audited and fixed. All hardcoded `<b>`/`<code>` in dynamic content replaced with bold()/code() helpers. Ruff clean. Import OK. |

## Completed items (recent additions on top)

| Item | Priority | Details | Date |
|---|---|---|---|
| Bugs #247-#255 (session 95) | correctness | user_ref() helper; deactivate_all/extra active bans; ban_flow: group reporting+PM notify+dedup; unban/appeal: deactivate_all; greeting: ChatJoinRequestHandler+all-groups enforcement; extraction _best_name str(uid); unban_flow cancel_schedule; conversation_timeout dead code removed (PTBUserWarning eliminated). CHANGELOG updated. | 2026-06-13 (s95) |
| Formatter consistency (#236-#246) | style/security | 11 files: netspeed.py, ban_flow.py, appeal_flow.py, admins.py, proof_flow.py, muting_flow.py, demote_flow.py, groups.py, reason_flow.py, help.py, stats_flow.py. All hardcoded `<b>` and `<code>` in dynamic content replaced with bold()/code() helpers. | 2026-06-13 (s93) |
| Final comprehensive audit | audit | Verified checking.py, banning.py, ban_flow.py, warning_flow.py, muting_flow.py, kicking_flow.py, unban_flow.py, appeal_flow.py, stats_flow.py, bans_db.py. All clean. No new bugs found. Total: #1-#235 final. | 2026-06-13 (s92) |
| Bug #235: run-bot.yml cron wrong | infra | Cron `55 4 * * *` (once daily) contradicts comment "Fires every 30 minutes". Self-chain fallback was effectively broken. Fixed to `*/30 * * * *`. | 2026-06-13 (s92) |
| Bug #234: docker-compose.yml four issues | correctness | env_file config.env to .env; MongoDB healthcheck missing --quiet+.ok+start_period; Redis start_period missing; networks.internal.internal:true removed (blocked bot internet access). | 2026-06-13 (s92) |
| Bug #233: auto-fix.yml --group dev | infra | uv sync --frozen --group dev fails; no dev group in pyproject.toml. Removed --group dev. | 2026-06-13 (s92) |
| Bug #232: netspeed.py no esc() on speedtest data | security | Speedtest API data (ISP, server name, country, IP, etc.) embedded in HTML template without esc(). Added esc() import and wrapped all external values. | 2026-06-13 (s92) |
| Bug #231: netspeed.py decorator order wrong | correctness | `@owner_only` was outermost, `@ratelimiter` second in both cmd_ping and cmd_speedtest. Fixed to `@ratelimiter` outermost, `@owner_only` second, `@log_execution` innermost per RULES.md. | 2026-06-13 (s91) |
| Feature: netspeed.py module | feature | /ping (alias /p) and /speedtest (alias /st), Founder-only, rate-limited 3/60s. speedtest-cli in thread executor. speedtest-cli==2.1.3 added to pyproject.toml. | 2026-06-13 (s91) |
| Bugs #221-230 fixed | correctness | shutdown sequential awaits, 9x q.answer-after-parse in stats+checking+admins | 2026-06-13 (s90w2) |
| Bug #220: RUF001 removed from ruff ignore | housekeeping | U+203A fully gone; stale ignore removed | 2026-06-13 (s90w1) |
| Bug #219: lint.yml CI gate | infra | Blocking ruff+import CI workflow created | 2026-06-13 (s90w1) |
| Bug #218: .dockerignore | infra | Missing dockerignore created | 2026-06-13 (s90w1) |
| Bugs #216-217: U+203A characters | typographic | admins.py and help.py final angle-quote cleanup | 2026-06-13 (s89w2) |
| Bugs #212-215: identity.py refusal gaps, disconnecting.py gather checks | correctness | 4 refusal table missing entries, 2 gather result checks | 2026-06-13 (s89w1) |
| Bugs #202-211 | correctness | connected_flow None guards, admins None guard, kicking_flow result check, dead bans index | 2026-06-13 (s88) |
| Bugs #187-201 | correctness | 15 bugs across ban_flow, muting_flow, reason_flow, groups, checking, warning_flow | 2026-06-13 (s87) |
| Bugs #179a-186 | correctness | 8 bugs across scheduler, redis_client, mongos, users_roles, cache | 2026-06-12 (s86) |
| Sessions 65-85 comprehensive audit | correctness | 114 bugs fixed (Bugs #65-178) across all modules | 2026-06-02 to 2026-06-12 |
| Sessions 1-64 comprehensive audit | correctness | 64 bugs fixed (Bugs #1-64), all P1/P2/P3/P4 items | 2026-06-02 to 2026-06-12 |
