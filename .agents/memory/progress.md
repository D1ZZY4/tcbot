---
name: Progress tracker
description: Item-by-item status of the improvement plan. Updated at each commit checkpoint.
---

# TCF Bot - Progress

**Last updated:** 2026-06-13 (session 91)

## Verification baseline

| Check | Result |
|---|---|
| `uv sync` | PASS |
| `uv pip install -e .` | PASS |
| `uv run python -c "import tcbot; print('import OK')"` | PASS (session 91: re-verified after netspeed.py addition) |
| `uv run python -m tcbot` | PASS by runtime evidence: MongoDB connected, indexes ensured, scheduler started, bot polling active |
| `uv run ruff format .` | PASS (73 files) |
| `uv run ruff check .` | PASS (All checks passed) |
| asyncio task-GC fix isolated test (session 43) | PASS: task registered on schedule, discarded on completion, report coroutine ran |
| annotation AST audit | PASS: 0 non-dunder function parameters missing type annotations |
| docs audit (session 74) | PASS: mapping.md top-level layout completed; 3 new Mermaid diagrams added; all code files audited clean |

## Completed items (recent additions on top)

| Item | Priority | Details | Date |
|---|---|---|---|
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
