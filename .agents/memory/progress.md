---
name: Progress tracker
description: Item-by-item status of the improvement plan. Updated at each commit checkpoint.
---

# TCF Bot - Progress

**Last updated:** 2026-06-13 (session 109)

## Verification baseline

| Check | Result |
|---|---|
| `uv sync` | PASS |
| `uv pip install -e .` | PASS |
| `uv run python -c "import tcbot; print('import OK')"` | PASS (re-verified session 93) |
| `uv run python -m tcbot` | PASS by runtime evidence: MongoDB connected, indexes ensured, scheduler started, bot polling active |
| `uv run ruff format .` | PASS (73 files) |
| `uv run ruff check .` | PASS (All checks passed, verified session 103) |
| asyncio task-GC fix isolated test (session 43) | PASS: task registered on schedule, discarded on completion, report coroutine ran |
| annotation AST audit | PASS: 0 non-dunder function parameters missing type annotations |
| docs audit (session 74) | PASS: mapping.md top-level layout completed; 3 new Mermaid diagrams added; all code files audited clean |
| Final comprehensive audit (session 92 final) | PASS: All remaining workflow, module, database files verified. 0 new bugs found. |
| Formatter consistency audit (session 93) | PASS: 11 files audited and fixed. All hardcoded `<b>`/`<code>` in dynamic content replaced with bold()/code() helpers. Ruff clean. Import OK. |
| Docs sync audit (session 100) | PASS: 9 docs updated to reflect sessions 95-99 code changes (user_ref, deactivate_all/extra, trigger=mute, str(uid) fallback). CHANGELOG updated. Ruff: 73 files clean. |
| Full module audit (session 99) | PASS: checking.py, check_flow.py, connecting.py, disconnecting.py, unbanning.py, admins.py, appeals.py, stats.py, broadcasting.py, maintenance.py, additional.py all clean. |
| Session 103 comprehensive audit | PASS: All 73 tcbot/ files fully audited. Bugs #271-#277 fixed. Docker/CI/scheduler all clean. Ruff: 73 files clean. |
| Session 109 comprehensive audit | PASS: Third full-pass audit of all primary moderation paths. No new bugs. ban_flow, greeting, scheduler, muting_flow, unban_flow, extraction, warning_flow, appeal_flow (approval), bans_db, mutes_db, checking, identity, decorators, muting, kicking, unbanning, banning, warnings, kicking_flow, appeals, connected_flow all verified CLEAN. Ruff: 73 files clean. Startup OK (27/27 indexes). Total: #1–#285. |
| Session 108 comprehensive audit | PASS: Second full-pass audit of all remaining areas — checking.py, warning_flow.py, check_flow.py (full), muting_flow.py (full), connected_flow.py (full), admins.py (555-836), ban_info.py, unbanning.py, kicking.py, dispatch.py, bans_db.py, groups_db.py, warns_db.py, kicks_db.py, mutes_db.py, users_roles.py, unban_flow.py, kicking_flow.py, demote_flow.py, promote_flow.py, broadcasting.py, disconnecting.py, proof_flow.py, reason_flow.py. Bug #285 (get_first_name L1 cache bypass) found and fixed. Ruff: 73 files clean. Total: #1–#285. |
| Session 107 fresh audit pass | PASS: mongos.py, groups_db.py, stats_flow.py, check_flow.py, broadcasting.py, maintenance.py, stats.py, connected_flow.py, kicking_flow.py, unban_flow.py, warning_flow.py, reason_flow.py, demote_flow.py, admins.py (full), checking.py, ban_flow.py all clean. Bugs #283+#284 (CI workflows) found and fixed. Ruff: 73 files clean. |
| Session 106 fresh audit pass | PASS: appeal_flow, warning_flow, warnings, checking, identity, banning, muting, kicking, extraction, decorators, reason_flow, proof_flow, demote_flow all clean. Bug #282 found and fixed. Ruff: 73 files clean. |

## Completed items (recent additions on top)

| Item | Priority | Details | Date |
|---|---|---|---|
| Bug #284 (session 107) | policy | lint.yml env block comment in Indonesian ("untuk import check") changed to English ("required for the import check") per project policy. | 2026-06-13 (s107) |
| Bug #283 (session 107) | infra | dependency-update.yml Create PR step: GH_TOKEN: ${{ secrets.GH_TOKEN }} changed to GH_TOKEN: ${{ github.token }} (built-in Actions token; always available without manual repo secret). | 2026-06-13 (s107) |
| Bug #281 (session 105) | performance | groups.py _toggle cache-miss branch: await q.answer() then await active_groups() were sequential. Parallelised with asyncio.gather(return_exceptions=True). Added import asyncio. | 2026-06-13 (s105) |
| Bug #280 (session 105) | performance | start.py _show_groups: await q.answer() then await active_groups() were sequential. Parallelised with asyncio.gather(return_exceptions=True). Added import asyncio. | 2026-06-13 (s105) |
| Bug #279 (session 104) | correctness | ban_flow._execute_ban / muting_flow._execute_mute+execute_unmute / unban_flow.execute_unban: MAIN_GROUP and EXEC_GROUP configured via env vars are not in federated_groups collection and thus excluded from active_groups(). Federation-banned/muted users were not kicked from primary groups on action; only removed on next join attempt. Fixed by appending cfg.main_group/cfg.exec_group to the groups list before fan_out when not already present. | 2026-06-13 (s104) |
| Bug #278 (session 104) | correctness | mutes_db.log_mute: audit record lacked duration_secs field. Timed mutes stored only user_id, chat_id, reason, admin_id, timestamp — no duration. Added duration_secs (int or None) keyword-only param to log_mute; updated _execute_mute to pass it. docs/databases/databases.md updated. | 2026-06-13 (s104) |
| Session 103 audit (session 103) | audit | Full audit sweep complete. T001: start.py, help.py, about.py, privacy.py, groups.py, modules/__init__.py, types.py verified clean; asyncio.gather/q.answer fixes + None guards added. T002: Dockerfile, docker-compose.yml, all 5 .github/workflows/*.yml audited. T003: dispatch.py, logger.py, utils/__init__.py, database/__init__.py, types.py, helper/__init__.py, workflows/__init__.py clean. T004: __main__.py, ban_info.py, extraction.py clean. Bugs #271-#277 fixed. CHANGELOG updated. Ruff: All checks passed (73 files). | 2026-06-13 (s103) |
| Bug #277 (session 103) | correctness | scheduler.py setup_schedules: CronTrigger(day_of_week=0) resolves to Sunday in APScheduler 4.x (Unix cron 0=Sunday), not Monday. Log message said "Monday". Changed to day_of_week="mon" for explicit, unambiguous scheduling. | 2026-06-13 (s103) |
| Bug #276 (session 103) | correctness | dispatch.py fan_out(): asyncio.CancelledError was caught by generic Exception handler and returned as a BaseException value rather than propagated. Added explicit CancelledError re-raise so bot shutdown is clean when multi-group fan_out is in flight. | 2026-06-13 (s103) |
| Bugs #271-#275 (session 103) | infra | #271: Dockerfile hiredis verification verbose. #272: docker-compose Redis healthcheck timeout 5s. #273: dependency-update.yml GITHUB_TOKEN (built-in, no manual secret). #274: lint.yml import check reverted to python -c "import tcbot" (was wrongly changed to python -m tcbot which hangs CI); Indonesian comment fixed to English. #275: Dockerfile hiredis verified. | 2026-06-13 (s103) |
| Session 102 audit (session 102) | audit | Audited 15 additional files: proof_flow.py, reason_flow.py, parse_logmsg.py, decorators.py, admins.py, users_cache.py, users_roles.py, promote_flow.py, connecting.py, disconnecting.py, groups_db.py, unbanning.py, appeals.py, check_flow.py, broadcasting.py — all clean, 0 new bugs. Em-dash/en-dash: 0 matches. Emoticon in identity.py: 0 matches. CHANGELOG.md updated for Bug #270. Ruff: All checks passed (73 files). | 2026-06-13 (s102) |
| Bug #270 (session 102) | correctness | extraction.py extract_target: reply to anonymous admin message skipped from_user (ANONYMOUS_BOT_ID) correctly but fell through to sender_chat which is the group itself. Added _skip_sender_chat flag to skip sender_chat when from_user is ANONYMOUS_BOT_ID. Full audit of ban_flow, greeting, bans_db, unban_flow, appeal_flow, banning, muting, kicking, warnings, demote_flow, connected_flow — all clean. | 2026-06-13 (s102) |
| Docs sync (session 100) | documentation | 9 docs updated to reflect sessions 95-99 code changes: user_ref in formatter table, deactivate_all/extra_active_bans in DB docs, trigger="mute" in demote/role/workflows docs, str(uid) fallback in check/stats docs, banning/appeal flow helpers updated. CHANGELOG updated. | 2026-06-13 (s100) |
| Bug #265 (session 99) | correctness | warnings.py cmd_warn_entry missing identity.staff_notice("warn", ...) before return in refusal guard; consistent with cmd_unwarn and cmd_resetwarns. CHANGELOG updated. | 2026-06-13 (s99) |
| Bugs #261-#264 (session 98) | correctness | banning/muting/kicking/warnings double-reply on resolve_and_check refusal; ban_flow F841 ban_duration; identity/checking numeric-string fallback guard; mention() dedup + "User {uid}"→str(uid) across 4 files. CHANGELOG updated. | 2026-06-13 (s98) |
| Bugs #256-#260 (session 97) | correctness | warning_flow execute_resetwarns user_ref; muting.py Demote trigger "kick"→"mute"; stats_flow user list user_ref; check_flow _async_const Any→Any; additional.py bold(). CHANGELOG updated. | 2026-06-13 (s97) |
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
