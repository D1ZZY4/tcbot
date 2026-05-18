# TCF Bot - Massive Refactor Task Plan

## Status Legend
- `[ ]` = Not started
- `[x]` = Completed
- `✅` = Batch fully complete

---

## Batch 1 – Add `@ratelimiter(limit, period)` Decorator to decorators.py
- [x] Add `ratelimiter(limit, period)` factory function to `decorators.py`
- [x] Factory returns a per-user sliding-window decorator (reuses existing `_RateLimiter`)
- [x] Decorator is non-blocking (zero delay for allowed requests)
- [x] Support custom `limit` and `period` parameters
- [x] Decorator order in stack: `@ratelimiter` outermost → `@owner_only/@staff_only/etc` → `@log_execution` innermost

✅ Batch 1 complete

---

## Batch 2 – Apply Decorators to `admins.py` (full modernization)
- [x] Apply `@decorators.ratelimiter(limit=5, period=60)` to `cmd_promote`
- [x] Apply `@decorators.ratelimiter(limit=5, period=60)` to `cmd_demote`
- [x] Apply `@decorators.ratelimiter(limit=3, period=60)` to `cmd_transfer`
- [x] Apply `@decorators.ratelimiter(limit=5, period=60)` to `cmd_promote_request`
- [x] Apply `@decorators.ratelimiter(limit=5, period=60)` to `cmd_promote_list`
- [x] Apply `@decorators.log_execution` to callback handlers missing it: `on_promote_role_btn`, `on_promote_role_cancel`, `on_demote_confirm`, `on_demote_cancel`
- [x] Ensure `__module_name__` and `__help_text__` are placed at TOP of file before all `def`/`async def`

✅ Batch 2 complete

---

## Batch 3 – Apply Decorators to `banning.py` and `unbanning.py`
- [x] Apply `@decorators.ratelimiter(limit=3, period=60)` to `cmd_ban_start` in `banning.py`
- [x] Apply `@decorators.log_execution` to `cmd_ban_start`
- [x] Apply `@decorators.ratelimiter` to `cmd_unban` in `unban_conv.py`
- [x] Apply `@decorators.log_execution` to `cmd_unban`
- [x] Ensure `__module_name__`/`__help_text__` at top in both files

✅ Batch 3 complete

---

## Batch 4 – Extract Kicking Conversation + Apply Decorators
- [x] Create `tcbot/modules/helper/workflows/kicking_conv.py` (extract from `kicking.py`)
- [x] Move `WAITING_REASON`, `WAITING_PROOF`, inline keyboards, all conversation states to `kicking_conv.py`
- [x] Update `kicking.py` to import from `kicking_conv.py`
- [x] Apply `@decorators.ratelimiter(limit=5, period=60)` + `@decorators.log_execution` to `cmd_kick_entry`
- [x] Ensure `__module_name__`/`__help_text__` at top of `kicking.py`

✅ Batch 4 complete

---

## Batch 5 – Create `reason_flow.py` with Shared Reason Utilities
- [x] Create `tcbot/modules/helper/workflows/reason_flow.py`
- [x] Add shared `parse_inline_reason(args, has_explicit_target)` utility
- [x] Add shared `reason_prompt_text(target_id, target_fname, action_label)` helper
- [x] Update `kicking_conv.py` and `muting_conv.py` to use shared utilities where applicable
- [x] Ensure no duplication of reason-parsing logic across files

✅ Batch 5 complete

---

## Batch 6 – Apply Decorators to `muting.py` + `muting_conv.py`
- [x] Apply `@decorators.ratelimiter(limit=5, period=60)` to `cmd_unmute` in `muting.py`
- [x] Apply `@decorators.ratelimiter(limit=5, period=60)` + `@decorators.log_execution` to `cmd_mute_start` in `muting_conv.py`
- [x] Ensure `__module_name__`/`__help_text__` at top of `muting.py`

✅ Batch 6 complete

---

## Batch 7 – Apply Decorators to `warnings.py` + `warning_conv.py`
- [x] Apply `@decorators.ratelimiter(limit=5, period=60)` to `cmd_unwarn`, `cmd_warnlist`, `cmd_resetwarns`
- [x] Apply `@decorators.ratelimiter` to `cmd_warn_start` in `warning_conv.py`
- [x] Apply `@decorators.log_execution` to warn entry and list handlers
- [x] Ensure `__module_name__`/`__help_text__` at top of `warnings.py`

✅ Batch 7 complete

---

## Batch 8 – Apply Decorators to `checking.py`
- [x] Apply `@decorators.ratelimiter(limit=8, period=30)` to `cmd_checkme` and `cmd_baninfo`
- [x] Apply `@decorators.log_execution` to `on_checkme_detail` and `on_checkme_back`
- [x] Ensure `__module_name__`/`__help_text__` at top

✅ Batch 8 complete

---

## Batch 9 – Apply Decorators to `stats.py` + workflow files
- [x] Apply `@decorators.ratelimiter(limit=8, period=30)` to `cmd_stats`
- [x] Apply `@decorators.log_execution` to callbacks in `stats_flow.py` and `stats_chats_flow.py`
- [x] Ensure `__module_name__`/`__help_text__` at top of `stats.py`

✅ Batch 9 complete

---

## Batch 10 – Apply Decorators to `groups.py`, `start.py`, `about.py`, `additional.py`
- [x] Apply `@decorators.ratelimiter(limit=8, period=30)` to all command handlers in these files
- [x] Apply `@decorators.log_execution` to any callbacks missing it
- [x] Ensure module metadata at top of each file

✅ Batch 10 complete

---

## Batch 11 – Apply Decorators to `broadcasting.py`, `connecting.py`, `disconnecting.py`
- [x] Apply `@decorators.ratelimiter(limit=3, period=60)` to `cmd_broadcast`
- [x] Apply `@decorators.ratelimiter(limit=5, period=60)` to `cmd_tcconnect` and disconnect
- [x] Apply `@decorators.log_execution` to any callbacks missing it
- [x] Ensure module metadata at top

✅ Batch 11 complete

---

## Batch 12 – Upgrade `help.py`: Add `/help <module>` Direct Command
- [x] Modify `cmd_help` to detect args and show specific module help directly
- [x] Support `/help ban`, `/help kick`, `/help admins`, etc.
- [x] Show fuzzy/closest match suggestion if module not found
- [x] Apply `@decorators.ratelimiter(limit=8, period=30)` to `cmd_help`
- [x] Apply `@decorators.log_execution` to help callbacks
- [x] Ensure module metadata at top

✅ Batch 12 complete

---

## Batch 13 – Apply Decorators to `greeting.py`, `maintenance.py`, `privacy.py`, `appeals.py`
- [x] Apply `@decorators.ratelimiter` to all command handlers
- [x] Apply `@decorators.log_execution` to callbacks missing it
- [x] Ensure module metadata at top of each file

✅ Batch 13 complete

---

## Batch 14 – Verify All Handler Declarations Follow `admins.py` Pattern
- [x] Check every module's `__handlers__` list is properly structured
- [x] Named filter constants `_CMD_FILTER` defined before `__handlers__`
- [x] All handlers grouped with section header `## ── Handlers ───`
- [x] No stray handler declarations outside `__handlers__`

✅ Batch 14 complete

---

## Batch 15 – Update `docs/architecture.md` with Full Cross-References
- [x] Update module table with all current modules
- [x] Add cross-reference links to all related `.md` files
- [x] Add section on new `reason_flow.py` and `kicking_conv.py`
- [x] Add section on `@ratelimiter` decorator

✅ Batch 15 complete

---

## Batch 16 – Update `docs/modules.md` with Cross-References
- [x] Update each module's description to match current state
- [x] Add links to `architecture.md`, `workflows.md`, `development.md`
- [x] Document new workflow files added

✅ Batch 16 complete

---

## Batch 17 – Update `docs/workflows.md` with Cross-References
- [x] Document `kicking_conv.py` and `reason_flow.py`
- [x] Add cross-references to all related docs
- [x] Ensure all ConversationHandler flows are documented

✅ Batch 17 complete

---

## Batch 18 – Update `docs/development.md` with Cross-References
- [x] Update decorator usage instructions to include `@ratelimiter`
- [x] Update "how to add a module" guide
- [x] Add cross-references to all related docs

✅ Batch 18 complete

---

## Batch 19 – Update `docs/index.md` with Cross-References
- [x] Ensure index links to all docs
- [x] Add summary of key architectural decisions
- [x] Add cross-references for all docs

✅ Batch 19 complete

---

## Batch 20 – Update `docs/agent-guidelines.md` with Cross-References
- [x] Document new decorator patterns
- [x] Add cross-references
- [x] Update any outdated information

✅ Batch 20 complete

---

## Batch 21 – Update `agents/CLAUDE.md` with New Patterns
- [x] Document `@ratelimiter(limit, period)` usage
- [x] Document `kicking_conv.py` and `reason_flow.py`
- [x] Update decorator stack examples
- [x] Add cross-references to all related docs

✅ Batch 21 complete

---

## Batch 22 – Update `agents/RULES.md` with New Constraints
- [x] Add rule: all handlers must use `@decorators.ratelimiter`
- [x] Update decorator order rules
- [x] Add cross-references

✅ Batch 22 complete

---

## Batch 23 – Update `agents/STYLE-CODE.md` with New Patterns
- [x] Add `@ratelimiter` to decorator order section
- [x] Update examples with full decorator stacks
- [x] Add cross-references

✅ Batch 23 complete

---

## Batch 24 – Update `agents/WORKFLOW.md` and `agents/STYLE-COMMENTS.md`
- [x] Add workflow notes for new conv/flow files
- [x] Update comment style examples if needed
- [x] Add cross-references

✅ Batch 24 complete

---

## Batch 25 – Update `agents/REPLIT.md`
- [x] Verify Replit environment notes are accurate
- [x] Add any new environment considerations
- [x] Add cross-references

✅ Batch 25 complete

---

## Batch 26 – Update `replit.md` (Project README)
- [x] Update key modules table with new files
- [x] Document `@ratelimiter` decorator
- [x] Update test count if changed
- [x] Add cross-references

✅ Batch 26 complete

---

## Batch 27 – Verify & Fix `unban_conv.py` + `unban_flow.py` Decorators
- [x] Add `@decorators.ratelimiter` and `@decorators.log_execution` to `cmd_unban`
- [x] Add `@decorators.mod_only` to `cmd_unban`
- [x] Verify decorators in `unban_flow.py`

✅ Batch 27 complete

---

## Batch 28 – Verify `connected_flow.py`, `warning_flow.py`, `muting_flow.py`
- [x] Add `@decorators.log_execution` to any callback/handler functions
- [x] Ensure all execute_* functions are properly structured
- [x] Verify no duplicate logic

✅ Batch 28 complete

---

## Batch 29 – Verify `appeal_flow.py` + `appeals.py`
- [x] Add `@decorators.ratelimiter` to appeal entry handler
- [x] Add `@decorators.log_execution` to appeal callbacks
- [x] Ensure module metadata at top

✅ Batch 29 complete

---

## Batch 30 – Final Verification: All Modules Have Correct Decorator Stacks
- [x] Audit every `cmd_*` handler across all module files
- [x] Audit every `on_*` callback handler
- [x] Confirm `@ratelimiter` → `@auth` → `@log_execution` order everywhere

✅ Batch 30 complete

---

## Batch 31 – Zero-Delay Verification: Parallelization Audit
- [x] Verify every handler that does multiple DB/API calls uses `asyncio.gather`
- [x] Check `kicking_conv.py` for any sequential awaits that can be parallelized
- [x] Check `reason_flow.py` functions for parallelization opportunities
- [x] Check all stats flow files for parallelization

✅ Batch 31 complete

---

## Batch 32 – Dead Code Removal Across All Modules
- [x] Remove unused imports from all files
- [x] Remove unused variables and functions
- [x] Remove any orphaned code

✅ Batch 32 complete

---

## Batch 33 – Cross-Reference Verification: All .md Files Link Each Other
- [x] Verify every `.md` in `docs/` links to at least 3 other docs
- [x] Verify every `.md` in `agents/` links to related docs
- [x] Verify `replit.md` links to all relevant docs

✅ Batch 33 complete

---

## Batch 34 – Verify `proof_conv.py` and `proof_flow.py` Are Canonical
- [x] Confirm proof collection is fully in `proof_conv.py` (conversation) and `proof_flow.py` (upload executor)
- [x] No inline proof logic in any module file
- [x] Add docstrings to both files

✅ Batch 34 complete

---

## Batch 35 – Ensure Consistent Handler Pattern in `__handlers__` Lists
- [x] All modules: named `_FILTER` constants before `__handlers__`
- [x] Aligned filter constants following `admins.py` pattern
- [x] Section divider `## ── Handlers ───` present in all module files

✅ Batch 35 complete

---

## Batch 36 – Full Test Suite Verification (pytest)
- [x] Run `python3 -m pytest tests/ -v` and confirm all 121 tests pass
- [x] Fix any tests broken by refactoring
- [x] Add tests for `ratelimiter` decorator if missing from `test_decorators.py`

✅ Batch 36 complete

---

## Batch 37 – Add Tests for `ratelimiter` Decorator
- [x] Add `test_ratelimiter_decorator` in `tests/test_decorators.py`
- [x] Test that handler is blocked after limit exceeded
- [x] Test that handler proceeds normally within limit
- [x] Test custom `limit` and `period` parameters

✅ Batch 37 complete

---

## Batch 38 – Add Tests for `reason_flow.py`
- [x] Create `tests/test_reason_flow.py`
- [x] Test `parse_inline_reason` utility
- [x] Test edge cases (empty args, reply vs explicit target)

✅ Batch 38 complete

---

## Batch 39 – Update `test_decorators.py` for New Patterns
- [x] Update existing decorator tests to reflect new stack
- [x] Ensure test coverage for `log_execution` with auth decorators stacked
- [x] Confirm all 121+ tests pass

✅ Batch 39 complete

---

## Batch 40 – Final Integration Test + Bot Restart Verification
- [x] Restart "Start application" workflow
- [x] Confirm no import errors in workflow logs
- [x] Run full test suite one final time
- [x] Verify `TASK.md` is fully up to date

✅ Batch 40 complete

---

## Batch 41 – `disconnecting.py` and `greeting.py` Module Review
- [x] Apply `@decorators.ratelimiter` to all handlers
- [x] Ensure module metadata at top
- [x] Apply `@decorators.log_execution` to callbacks

✅ Batch 41 complete

---

## Batch 42 – `maintenance.py` and `privacy.py` Module Review
- [x] Apply `@decorators.ratelimiter` to all handlers
- [x] Ensure module metadata at top
- [x] Apply `@decorators.log_execution` to callbacks

✅ Batch 42 complete

---

## Batch 43 – `ban_conv.py` Review and Decorator Application
- [x] Add `@decorators.log_execution` to proof callbacks
- [x] Ensure proof collection handlers are consistent with `proof_conv.py` pattern

✅ Batch 43 complete

---

## Batch 44 – `connected_flow.py` and `unban_flow.py` Review
- [x] Verify execute functions are properly async
- [x] Ensure proper error handling and logging
- [x] No duplicate logic with other modules

✅ Batch 44 complete

---

## Batch 45 – `promote_flow.py` Decorator & Docstring Update
- [x] Add docstrings to `_execute_promote`
- [x] Verify async parallelization is optimal
- [x] Ensure no dead code

✅ Batch 45 complete

---

## Batch 46 – Database Layer Audit
- [x] Verify all DB functions in `admins_db.py`, `bans_db.py`, `roles_db.py` are properly async
- [x] Verify all DB functions in `users_db.py`, `groups_db.py`, `queues_db.py` are properly async
- [x] No raw `col()` calls in module handlers

✅ Batch 46 complete

---

## Batch 47 – Utils Audit: `dispatch.py`, `prefixes.py`, `logger.py`, `timedate_format.py`
- [x] Verify `fan_out()` semaphore is appropriate
- [x] Verify `build_prefixed_filters` and `parse_cmd_args` are correct
- [x] No dead code

✅ Batch 47 complete

---

## Batch 48 – `tcbot/__init__.py` and `tcbot/__main__.py` Audit
- [x] Verify config is loaded correctly
- [x] Verify `global_rate_limit_handler` is registered at group -1
- [x] No dead imports

✅ Batch 48 complete

---

## Batch 49 – Final Documentation Cross-Reference Verification
- [x] Every `.md` file has at least one `## Related documentation` section
- [x] All links are valid (no broken references)
- [x] `replit.md` reflects final state of project

✅ Batch 49 complete

---

## Batch 50 – Final Report and Cleanup
- [x] All decorator stacks verified across all handlers
- [x] All `.md` files updated and cross-referenced
- [x] All tests passing
- [x] No dead code remaining
- [x] `TASK.md` fully checked off
- [x] Bot workflow running cleanly

✅ Batch 50 complete

---

## Summary of Key Decisions

| Item | Decision |
|---|---|
| `@ratelimiter` | Factory decorator in `decorators.py`, per-user sliding window, custom `limit`/`period` |
| Proof placement | Already in `proof_conv.py` (conversation states) + `proof_flow.py` (upload executor) |
| Reason placement | Create `reason_flow.py` with shared utilities; `kicking_conv.py` extracts kick conversation |
| `helpc_*` unification | Already unified via `on_help_topic_any`; add `/help <module>` direct command to `cmd_help` |
| Handler structure | All modules follow `admins.py` pattern: named `_FILTER` constants + aligned `__handlers__` |
| Decorator order | `@ratelimiter` → `@owner_only/@staff_only/@mod_only/@basic_mod_only` → `@log_execution` |
