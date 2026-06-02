---
name: Sequential await audit
description: Results of the full codebase audit for sequential awaits on independent operations (RULES.md Forbidden Action). Records which modules were fixed and which are correct-by-design.
---

# Sequential Await Audit — TCF Bot

**Why this matters:** RULES.md designates sequential awaits on independent async operations a Forbidden Action. Every moderation handler calls into the same helpers, so fixing a central function (e.g. `identity.classify`) fixes latency for all callers at once.

**How to apply:** When adding or reviewing any async function, check whether any two consecutive `await` calls are truly independent. If yes, use `asyncio.gather`. Comment new gather calls with `# *` per STYLE-CODE.md.

## Fixed modules

| Module | What was fixed | Session |
|---|---|---|
| `tcbot/modules/admins.py` | `cmd_promote` and `cmd_demote`: `identity.classify + db.users_roles.get_effective_role` gathered | s5 |
| `tcbot/modules/stats.py` | Refactored `_ack_and_render(q, data_coro)`: `q.answer()` + heavy DB coroutine now parallel across 12 handlers | s5 |
| `tcbot/modules/groups.py` | `_toggle` cache-hit branch: `q.answer()` + `safe_edit()` now gathered | s5 |
| `tcbot/modules/helper/identity.py` | `classify()`: `get_user_mention_data` + `get_effective_role` now gathered (high-impact — affects every moderation command) | s5 |

## Correct-by-design (sequential intentional)

| Module | Reason sequential is correct |
|---|---|
| `broadcasting.py` | Status reply must appear before fan_out begins; status text depends on `len(groups)` |
| `maintenance.py` | Same pattern as broadcasting — status before fan_out |
| `disconnecting.py` | Each guard check (`is_connected`, role verify) must succeed before the next step |
| `decorators.py` | Auth checks (`is_staff`, `get_effective_role`) guard `func(update, ctx)` — cannot parallelize |
| `unban_flow.py` | `get_active_ban` result controls early exit; subsequent reply depends on it |
| `reason_flow.py` | Each state step produces data needed by the next |
| `warning_flow.py` | `add_warn` result (count) drives the auto-ban threshold check |
| `appeal_flow.py` | Already uses `asyncio.gather` at line 342; staff check gates all subsequent logic |
| `help.py` | All internal helpers (`_render_help_index`, `_show_module`) already use `asyncio.gather` |
| `start.py` | `_show_groups` already uses `asyncio.gather`; command handler awaits are single-step |
| `greeting.py` | Single-await handlers by necessity |
| `ban_flow.py` | Already correct at time of first audit |
| `banning.py` | Already correct |
| `kicking.py` | Already correct |
| `muting.py` | Already correct |
| `checking.py` | Already correct |
| `connecting.py` | Already correct |
| `kick_flow.py` | No sequential await patterns found |
| `mute_flow.py` | No sequential await patterns found |
| `demote_flow.py` | if/else branches — single await per branch by necessity |
| `promote_flow.py` | Conditional logic gates each step |

## Test coverage for classify()

13 new async tests added to `tests/test_identity.py` covering:
- Self / this_bot / Telegram / other_bot early returns
- All four role-based identity kinds (founder, admin, developer, tester)
- No-role → user
- fname fallback (None, "User <id>", explicit)
- Assertion that both DB calls are invoked (validates the gather)
