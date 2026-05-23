# TCF Bot — Execution Plan

This document is the authoritative reference for how the project runs, where the known bugs are, what the improvement strategy is, and how sessions are tracked. Update it whenever the state of the project changes.

---

## How the Project Runs End-to-End

### Startup Sequence

```
python3 -m tcbot
  │
  ├── tcbot/__init__.py
  │     Loads config from env vars (Replit Secrets + Replit shared env).
  │     Builds immutable Configs dataclass → exposes thin _CfgAdapter as cfg.
  │     load_dotenv(config.env, override=False) as local-dev fallback only.
  │
  └── tcbot/__main__.py : main()
        ├── setup_logging()
        │     BotLogFormatter: [HH:MM] [DD-MM-YYYY] | community | L - module:line - msg
        │     Third-party loggers (httpx, telegram, motor, pymongo) capped at WARNING.
        │
        ├── start_keepalive()
        │     Flask thread on 0.0.0.0:8080 — GET / returns "OK".
        │     Daemon thread; exits when main process exits.
        │
        ├── ApplicationBuilder()
        │     .token(cfg.bot_token)
        │     .post_init(_post_init)
        │     .concurrent_updates(True)        — independent updates processed in parallel
        │     .connection_pool_size(8)          — API call pool
        │     .get_updates_connection_pool_size(4)
        │     .read_timeout(15) .write_timeout(15) .connect_timeout(10) .pool_timeout(5)
        │
        ├── Handler registration (in order):
        │     group -1 : TypeHandler(Update, global_rate_limit_handler)   — runs first
        │     group  0 : all module __handlers__ via get_handlers()
        │     group 10 : MessageHandler(groups & text & ~ANY_CMD_FILTER, _update_member_cache)
        │     error    : _error_handler
        │
        └── app.run_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)
```

### _post_init (async, runs after PTB builds the Application)

```
_post_init(app)
  ├── connect()              Motor client → MongoDB Atlas, 10s timeout, ping verify
  ├── ensure_indexes()       11 indexes created in parallel via asyncio.gather()
  ├── ensure_initial_owner() Seed owner if tc_owners is empty
  └── error_reporter.attach(bot, log_errors_chat, log_errors_thread)
      loop.set_exception_handler(asyncio exception handler)
```

### Request Processing Pipeline

```
Telegram Update arrives via long poll
  │
  ├── group -1: global_rate_limit_handler
  │     CallbackQuery → 20 presses / 10 s per user
  │       denied: show_alert toast ("⏳ slow down…"), raise ApplicationHandlerStop
  │     Command text → 8 commands / 30 s per user
  │       denied: reply text + raise ApplicationHandlerStop
  │     Everything else (conversation text, join events, etc.) → always passes
  │
  ├── group 0: module handlers
  │     Each command handler carries (outermost → innermost):
  │       @decorators.ratelimiter(limit, period)   per-handler fine-grained throttle
  │       @decorators.owner_only / staff_only / mod_only / basic_mod_only
  │       @decorators.log_execution                opt-in: entry/exit/elapsed ms at DEBUG
  │
  └── group 10: _update_member_cache
        Runs only for text messages in connected groups that are not commands.
        Calls users_db.upsert_user() to keep the member cache fresh.
```

### Module Discovery

`tcbot/modules/__init__.py` — runs at import time:

1. `_discover_modules()` — globs `*.py` in `tcbot/modules/`, strips `__init__.py`
2. `_filter_modules()` — applies `MODULES_LOAD` (whitelist) and `MODULES_NO_LOAD` (blacklist)
3. `get_handlers()` — imports each module, collects `__handlers__` lists in discovery order

### Database Layer

All DB access is async via Motor. Connection is a module-level singleton (`_db` in `mongos.py`). Handlers never call `col()` directly — always go through the per-collection helper files.

```
Collections and owners:
  bans               bans_db.py        Federation bans (active / historical)
  tc_owners          admins_db.py      Single-document owner record
  tc_admins          admins_db.py      Admin list with promotion metadata
  tc_roles           roles_db.py       Developer and Tester role assignments
  federated_groups   groups_db.py      Connected groups with is_active flag
  pending_joins      groups_db.py      Groups awaiting federation approval
  member_cache       users_db.py       User profile snapshot cache
  warns              warns_db.py       Per-group warning records
  kicks              kicks_db.py       Kick log entries
  mutes              mutes_db.py       Mute log entries
  promotion_requests queues_db.py      Admin promotion request queue
```

### In-Memory Cache Layer (`tcbot/database/cache.py`)

| Cache | Key | TTL | Invalidated by |
|---|---|---|---|
| `effective_role_cache` | `user_id` | 60 s | Any role/admin/owner write |
| `owner_id_cache` | constant | no TTL | `set_owner()` |
| `connected_cache` | `chat_id` | no TTL | `add_group()`, `deactivate_group()` |
| `active_groups_cache` | constant | no TTL | `add_group()`, `deactivate_group()` |

### Fan-out Dispatcher (`tcbot/utils/dispatch.py`)

`fan_out(coros, max_concurrent=10)` runs a list of coroutines concurrently bounded by `asyncio.Semaphore(10)`. Returns a list matching input order: result or captured `BaseException`. Never raises. Used for all multi-group operations (ban enforcement, mute, kick, unban sweep).

### Error Handling — 3 Layers

| Layer | Where | Catches |
|---|---|---|
| 1 | PTB `app.add_error_handler(_error_handler)` | All unhandled handler exceptions |
| 2 | `asyncio loop.set_exception_handler(...)` | `create_task()` / background task failures |
| 3 | `TelegramErrorHandler` on root logger | All `log.error()` / `log.critical()` calls |

All three layers route to `error_reporter.report_exc()` which ships a formatted HTML message to the `LOGS_ERRORS` channel.

---

## Role System

| Role | Rank | Collection |
|---|---|---|
| founder | 4 | `tc_owners` |
| admin | 3 | `tc_admins` |
| developer | 2 | `tc_roles` |
| tester | 1 | `tc_roles` |

**Canonical resolver:** `roles_db.get_effective_role(user_id)` → queries owner, admin, and role collections in parallel via `asyncio.gather()`, caches for 60 s.

**Permission check:** `roles_db.can_act_on(executor_id, target_id)` → executor rank must be strictly greater than target rank.

**Auto-demote:** When any role holder is banned or kicked, `role_guard.auto_demote()` removes their role, posts a log entry, and sends them a DM notification. Fires unconditionally before the moderation action executes.

**Decorator minimum ranks:**

| Decorator | Minimum role | Used for |
|---|---|---|
| `owner_only` | founder (4) | Transfer ownership, direct commands |
| `staff_only` | admin (3) | Promotion requests, staff lists |
| `mod_only` | developer (2) | Ban / unban |
| `basic_mod_only` | tester (1) | Kick / mute / warn |

---

## Conversation Flows Summary

| Flow | Factory | States | Entry trigger |
|---|---|---|---|
| Ban | `ban_flow.ban_conversation(entry)` | `WAITING_PROOF` | `/tcban` |
| Kick | `reason_flow.build_modaction_conv(...)` | `WAITING_REASON`, `WAITING_PROOF` | `/tckick` |
| Mute | `reason_flow.build_modaction_conv(...)` | `WAITING_REASON`, `WAITING_PROOF` | `/tcmute` |
| Warn | `reason_flow.build_modaction_conv(...)` | `WAITING_REASON`, `WAITING_PROOF` | `/tcwarn` |
| Appeal | `appeal_flow.build_handler()` | `WAITING_APPEAL`, `WAITING_CONFIRM` | `/start appeal_<ban_id>` |

**Rule:** There are no `*_conv.py` files. Every `ConversationHandler` is built inside a `*_flow.py` file via a factory function. The module file defines `*_CMDS` filters, the entry point, and `__handlers__ = [factory(entry_fn, *_CMDS)]` (see `admins.py`).

---

## Bug Fix Priorities

### P0 — Critical

| # | File | Issue | Fix |
|---|---|---|---|
| 1 | `agents/REPLIT.md` | Says "never use Replit Secrets" — contradicts current setup | Update to reflect actual Replit Secret usage |
| 2 | `README.md` | Still says all secrets go in `config.env` — wrong for Replit deployment | Update Quick Start and Configuration sections |

### P1 — High

| # | File | Issue | Fix |
|---|---|---|---|
| 3 | `docs/agent-guidelines.md` | Duplicates `agents/CLAUDE.md` — stale, confusing | Delete; merge unique content into `agents/CLAUDE.md` |
| 4 | `PLAN.md` | Was a placeholder with no real execution plan | Replaced by this document |
| 5 | `docs/workflows.md` | Content was truncated; per-flow descriptions missing | Expanded in this session |

### P2 — Medium

| # | File | Issue | Fix |
|---|---|---|---|
| 6 | `appeal_flow.py` appeal lock check | Duplicate datetime logic vs `appeals.reviewer_locked_out` | Resolved — shared guard + `timedate_format` |
| 7 | Multiple modules | Bare `except: pass` or `except Exception: pass` with no log line — silent production failures | Replace with at minimum `log.debug(...)` |

### P3 — Low

| # | File | Issue | Fix |
|---|---|---|---|
| 8 | `agents/REPLIT.md` | Still references port 5000 — bot runs on 8080 in Replit | Update port reference |
| 9 | `tcbot/database/cache.py` | Potential thundering-herd if N coroutines all miss the same cache key simultaneously | Add asyncio.Lock per key |

---

## Code Improvement Strategy

### Principles (in order of priority)

1. **No dead code** — Every unused import, variable, or function is removed immediately.
2. **No duplicate logic** — If the same render or format pattern appears in two modules, extract it.
3. **No silent fallbacks** — Failed operations are logged explicitly; `pass` in `except` blocks is forbidden.
4. **Consistent style** — Every file follows `agents/STYLE-CODE.md` and `agents/STYLE-COMMENTS.md` exactly.
5. **Parallel I/O** — Any two independent async operations must be gathered, never awaited sequentially.

### What NOT to Do

- Do not add new packages to `requirements.txt`
- Do not use `typing.Optional`, `typing.List`, `typing.Tuple` — use built-in generics
- Do not use `datetime.utcnow()` or inline `datetime.now(timezone.utc)` — use `tcbot.utils.timedate_format` (`utc_now()`, `to_utc()`, etc.)
- Do not create `*_conv.py` files — all `ConversationHandler`s live in `*_flow.py`
- Do not call `col()` directly from module handlers
- Do not use `q._bot` — use `ctx.bot`
- Do not inline imports inside function bodies
- Do not use `mention(x) + code(x)` — pick one per context

---

## Performance and Stability Goals

### Performance

| Goal | Mechanism |
|---|---|
| Zero per-request DB overhead for role checks | `effective_role_cache` 60 s TTL, invalidated on writes |
| Zero sequential loops for multi-group actions | `fan_out()` with `Semaphore(10)` |
| Parallel permission + target resolution at command entry | `asyncio.gather()` in every entry point |
| Fast group membership check | `connected_cache` boolean, no TTL |
| Minimal poll latency | `concurrent_updates=True`, pool 8+4 |

### Stability

| Goal | Mechanism |
|---|---|
| No crashes from Telegram API failures in group loops | `try/except` around every `.send_*` / `.ban_*` inside `fan_out` |
| No crashes from DB failures at startup | 10 s `serverSelectionTimeoutMS`, clean error before exit |
| No crashes from bad user input | All entry points validate target + reason before state transition |
| No infinite error loops | `error_reporter` uses `print()` on send failure — never `log.error()` |
| No memory leaks in rate limiter | Stale buckets pruned eagerly on every `.check()` call |
| Bot survives `ConversationHandler` timeouts | `ConversationHandler.END` returned on all fallback paths |

---

## Session Progress

### Session 1 — Environment Setup ✅
- Migrated from Replit Agent to Replit environment
- Stored `BOT_TOKEN` and `MONGODB_URI` in Replit Secrets
- All 121 tests pass, bot starts and connects to MongoDB
- Cleaned `config.env` of hardcoded secrets

### Session 2 — Documentation Overhaul ✅ (current)
- Rewrote `PLAN.md` (this document)
- Rewrote all `agents/*.md` as comprehensive AI agent instructions
- Rewrote all `docs/*.md` as thorough developer documentation
- Removed duplicate `docs/agent-guidelines.md`
- Updated `README.md`

### Session 3 — Code Quality Pass (planned)
- [ ] Audit every module for 3-layer decorator stack compliance
- [ ] Fix all bare `except: pass` blocks
- [ ] Fix datetime inconsistency in `appeal_flow.py`
- [ ] Remove any dead code found during documentation pass

### Session 4 — Stability Hardening (planned)
- [ ] Add asyncio lock to cache thundering-herd issue
- [ ] Review ConversationHandler fallback paths for completeness
- [ ] Verify auto-demote fires on all required code paths
- [ ] Expand test coverage for appeal flow edge cases

### Session 5 — Full Codebase Read-Through & Audit ✅

Complete read of every file in the project (50+ source files, all tests, all docs, all config).

**Ruff result:** `uv tool run ruff check . --select E4,E7,E9,F,I` → **All checks passed — 0 issues found.**

Corrections applied:

- [x] `docs/development.md` — test count updated 121 → 134
- [x] `agents/REPLIT.md` — test count updated 121 → 134
- [x] `pyproject.toml` — `requires-python` updated `>=3.12` → `>=3.13`; `target-version` updated `py312` → `py313`
- [x] `Dockerfile` — base image updated `python:3.12-slim` → `python:3.13-slim`

No source code changes required — zero Ruff violations, zero logic/style issues found.
All 134 tests pass.

---

## Code Quality Checklist (Task File — Session 5)

### Ruff
- [x] Run `uv tool run ruff check . --select E4,E7,E9,F,I` — 1 violation found (unused import in logger.py, fixed as part of Issue 8)
- [x] Run `uv tool run ruff format .` — no formatting changes needed; codebase already conforms

### Issue 1 — Missing `from __future__ import annotations`
- [x] `tests/__init__.py` — already present at line 9; no change needed

### Issue 2 — Exception chaining never used
- [x] Audited all 30+ `except ... as exc:` blocks; none re-raise a new exception without `from exc`. The one true re-raise (`_owner_id_from_env` in `__init__.py`) already uses `raise RuntimeError(...) from exc`. All other blocks log and continue; bare `raise` in `warns_db.py` correctly re-raises the caught exception. No chaining gaps found.

### Issue 3 — `# type: ignore` suppressions in `cache.py`
- [x] `TTLCache` is already `Generic[T]`; no `# type: ignore` comments exist anywhere in `cache.py`. Issue pre-resolved.

### Issue 4 — Weakly-typed parameters
- [x] `prefixes.py` — `dispatch_alt_prefix` already uses `_UpdateLike` / `_ContextLike` Protocol types
- [x] `extraction.py` — `get_reason()` already uses `_UpdateLike` / `_ContextLike` Protocol types
- [x] `dispatch.py` — `fan_out` already uses a proper `TypeVar T` bound to `Awaitable`; issue pre-resolved

### Issue 5 — `list[dict]` anti-pattern in DB layer
- [x] All DB helpers already return typed shapes (`BanDoc`, `AdminDoc`, `GroupDoc`, `UserDoc`, `WarnDoc`, `PromotionRequestDoc`, etc.) from `documents.py`. Issue pre-resolved.

### Issue 6 — Module-level mutable state
- [x] `ban_flow.py` — `_albums` / `_album_meta` are intentional asyncio-safe module-level dicts; concurrency is single-threaded via the event loop. Accepted design; no refactor warranted without clear regression risk.
- [x] `prefixes.py` — `_REGISTRY` is an intentional asyncio-safe module-level dict; populated at import time and only read thereafter.
- [x] `error_reporter.py` — `_bot` / `_chat_id` / `_thread_id` set once via `attach()` in `_post_init`; safe under asyncio. Accepted design.

### Issue 7 — Bare `except Exception: pass` (silent failures)
- [x] `tcbot/__init__.py:parse_list` — logs with `logging.getLogger(__name__).debug(...)` on `(ValueError, SyntaxError)`. Not bare.
- [x] `tcbot/__main__.py` — asyncio handler creation failure logs via `log.debug("Failed to schedule async error report: %s", err)`
- [x] `tcbot/modules/helper/decorators.py` — all rate-limit reply failures log via `log.debug(...)`
- [x] `tcbot/modules/connecting.py` — permission check failure logs via `log.debug(...)` and replies with an error message

### Issue 8 — Dead code in `logger.py`
- [x] Removed unused `project_name: str` parameter from `BotLogFormatter.__init__`; signature is now `__init__(self) -> None`
- [x] Updated `setup()` call from `BotLogFormatter(cfg.community_name)` to `BotLogFormatter()`
- [x] Removed now-unused `from tcbot import cfg` import in `logger.py` (Ruff F401 fix)

### Issue 9 — Unused advanced type patterns
- [x] Created `tcbot/database/types.py` with `NewType` domain primitives: `UserId`, `GroupId`, `ChatId`, `BanId`
- [x] Added `Literal` type aliases to `documents.py`: `BanStatus`, `RoleName`, `RequestStatus`
- [x] Applied `RoleName` to `RoleDoc.role`; `RequestStatus` to `PromotionRequestDoc.status`
- [x] Applied `UserId` / `GroupId` / `ChatId` / `BanId` throughout all `TypedDict` document definitions
- [x] `Protocol` classes for duck-typed interfaces already exist in `prefixes.py` and `extraction.py`; discriminated unions deferred (no current state machine ambiguity warrants them)
