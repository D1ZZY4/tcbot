# Architecture — TCF Bot

This document explains the runtime shape and internal architecture of TCF Bot.  
For per-module API details, see [docs/modules.md](modules.md).  
For ConversationHandler flows, see [docs/workflows.md](workflows.md).

---

## Startup Sequence

```
python3 -m tcbot
  │
  ├── tcbot/__init__.py
  │     Reads env vars (Replit Secrets + Replit shared env + config.env fallback).
  │     Builds immutable Configs dataclass.
  │     Exposes thin _CfgAdapter as the global cfg singleton.
  │
  └── tcbot/__main__.py : main()
        ├── setup_logging()
        │     Installs BotLogFormatter on the root logger.
        │     Caps noisy third-party loggers (httpx, telegram, motor, pymongo) at WARNING.
        │
        ├── start_keepalive()
        │     Starts Flask in a daemon thread on 0.0.0.0:5000.
        │     GET / returns "OK" for health checks.
        │
        ├── ApplicationBuilder()
        │     .token(cfg.bot_token)
        │     .post_init(_post_init)               async hook, runs after PTB init
        │     .concurrent_updates(True)            independent updates in parallel
        │     .connection_pool_size(8)             API call pool
        │     .get_updates_connection_pool_size(4)
        │     .read_timeout(15)
        │     .write_timeout(15)
        │     .connect_timeout(10)
        │     .pool_timeout(5)
        │
        ├── Handler registration (strictly ordered):
        │     group -1 : TypeHandler(Update, global_rate_limit_handler)  — runs first
        │     group  0 : all module __handlers__ via get_handlers()
        │     group 10 : MessageHandler(connected group text, _update_member_cache)
        │     error    : _error_handler
        │
        └── app.run_polling(drop_pending_updates=True, allowed_updates=ALL_TYPES)
```

### _post_init (async, runs after PTB builds the Application)

```
_post_init(app)
  ├── connect()
  │     Motor client → MongoDB Atlas, serverSelectionTimeoutMS=10s, ping verify.
  │     Logs "MongoDB connected → <db_name>" on success.
  │     Calls sys.exit(1) with a clear message on failure.
  │
  ├── ensure_indexes()
  │     Creates 11 MongoDB indexes in parallel via asyncio.gather().
  │     Idempotent — safe to call on every startup.
  │
  ├── ensure_initial_owner(cfg.initial_owner_id)
  │     Inserts the configured owner into tc_owners if the collection is empty.
  │
  └── error_reporter.attach(bot, log_errors_chat, log_errors_thread)
      loop.set_exception_handler(asyncio exception handler)
```

---

## Request Processing Pipeline

```
Telegram Update (via long poll)
  │
  ├── PTB concurrent_updates=True
  │     Each update gets its own asyncio task unless it has the same conversation key.
  │
  ├── group -1: global_rate_limit_handler
  │     CallbackQuery → 20 presses / 10 s per user
  │       denied: show_alert toast, raise ApplicationHandlerStop
  │     Command text  →  8 commands / 30 s per user
  │       denied: reply text, raise ApplicationHandlerStop
  │     All other update types → always passes through
  │
  ├── group 0: registered module handlers
  │     Checked in priority order defined by modules/__init__.py.
  │     Each handler may carry:
  │       @ratelimiter(limit, period)    per-handler fine-grained throttle
  │       @owner_only / staff_only / mod_only / basic_mod_only
  │       @log_execution                 opt-in DEBUG tracing
  │
  └── group 10: _update_member_cache
        Only fires on text messages in connected groups that are not commands.
        Calls users_db.upsert_user() to keep the member profile cache fresh.
```

---

## Module Discovery

`tcbot/modules/__init__.py` runs at import time:

1. `_discover_modules()` — globs `tcbot/modules/*.py`, excludes `__init__.py`
2. `_filter_modules()` — applies `MODULES_LOAD` whitelist and `MODULES_NO_LOAD` blacklist from env
3. `get_handlers()` — imports each module, collects `__handlers__` lists in discovery order; respects `_PRIORITY_FIRST` and `_PRIORITY_LAST` override lists

Modules are identified by `__module_name__`. Modules with `__module_name__ = None` are loaded but hidden from `/help`.

---

## Type System

`tcbot/database/types.py` defines `NewType` domain primitives for every ID field used in the database layer:

| Type | Base | Represents |
|---|---|---|
| `UserId` | `int` | Telegram user ID |
| `GroupId` | `int` | Telegram supergroup / group chat ID |
| `ChatId` | `int` | Generic Telegram chat ID |
| `BanId` | `str` | Short alphanumeric federation ban identifier |

`tcbot/database/documents.py` defines `TypedDict` shapes for every MongoDB document and `Literal` type aliases:

| Alias | Values |
|---|---|
| `BanStatus` | `"active"` / `"expired"` / `"revoked"` |
| `RoleName` | `"founder"` / `"admin"` / `"developer"` / `"tester"` |
| `RequestStatus` | `"pending"` / `"approved"` / `"rejected"` |

All `NewType` and `TypedDict` definitions are structural at runtime (zero overhead). Import from these modules when adding new code to benefit from nominal type safety.

---

## Database Schema

### Collections

| Collection | Key Fields |
|---|---|
| `bans` | `ban_id`, `banned_user_id`, `is_active`, `reason`, `admin_user_id`, `proof_message_id`, `log_message_id`, `timestamp`, `review_message_id` |
| `tc_owners` | `user_id` (single document) |
| `tc_admins` | `user_id`, `promoted_by`, `promoted_date` |
| `tc_roles` | `user_id`, `role` (`developer`/`tester`), `assigned_by`, `assigned_at` |
| `federated_groups` | `chat_id`, `title`, `added_by`, `added_date`, `is_active` |
| `pending_joins` | `chat_id`, `title`, `owner_id`, `message_id`, `added_date` |
| `member_cache` | `user_id`, `first_name`, `username`, `updated_at` |
| `warns` | `user_id`, `chat_id`, `count`, `reasons[]`, `updated_at` |
| `kicks` | `user_id`, `chat_id`, `admin_id`, `reason`, `timestamp` |
| `mutes` | `user_id`, `chat_id`, `admin_id`, `reason`, `duration_secs`, `timestamp` |
| `promotion_requests` | `request_id`, `user_id`, `requested_by`, `status`, `timestamp` |

### Indexes (created by `mongos.ensure_indexes()`)

```
bans:              [banned_user_id + is_active], [ban_id]
tc_owners:         [user_id]
tc_admins:         [user_id]
tc_roles:          [user_id]
federated_groups:  [chat_id], [is_active]
pending_joins:     [chat_id]
member_cache:      [user_id]
warns:             [user_id + chat_id]
kicks:             [user_id + chat_id]
mutes:             [user_id + chat_id]
promotion_requests:[user_id], [request_id]
```

All indexes are created with `background=True` — startup is not blocked if MongoDB is slow.

---

## Caching Layer

`tcbot/database/cache.py` provides in-memory TTL caches backed by a simple dict:

| Cache | Key | TTL | Invalidated by |
|---|---|---|---|
| `effective_role_cache` | `user_id` | 60 s | Any role/admin/owner write (`set_role`, `add_admin`, `set_owner`, etc.) |
| `owner_id_cache` | constant | no TTL | `set_owner()` |
| `connected_cache` | `chat_id` | no TTL | `add_group()`, `deactivate_group()` |
| `active_groups_cache` | constant | no TTL | `add_group()`, `deactivate_group()` |

Caches use `CACHE_MISS` as a sentinel (distinct from `None`). Every cache read checks for `CACHE_MISS`, then falls through to the database on miss.

---

## Fan-out Dispatcher

`tcbot/utils/dispatch.py:fan_out(coros, max_concurrent=10)`

Used for all operations that must touch multiple groups simultaneously (ban enforcement, unban sweep, mute, kick, group sweep). 

Properties:
- Runs all coroutines concurrently, bounded by `asyncio.Semaphore(10)`
- Returns results in input order: each element is the coroutine's return value or the captured `BaseException`
- Never raises — all exceptions are captured per-coroutine
- Callers count `isinstance(r, BaseException)` to tally errors

---

## Config Singleton

`tcbot/__init__.py` defines two classes:

**`Configs`** — frozen dataclass. All fields typed. Loaded from env vars in `Configs.load()`.

**`_CfgAdapter`** — thin accessor wrapping a `Configs` instance. Exposes the same fields as properties. Parses `LOGS`, `PROOFS`, `APPEALS` into `(chat_id, thread_id | None)` tuples.

**`cfg`** — module-level singleton of type `_CfgAdapter`. Imported as `from tcbot import cfg` everywhere.

**Never** access `configs` (the raw dataclass) from module code. Always use `cfg`.

---

## Error Handling — Three Layers

| Layer | Mechanism | Catches |
|---|---|---|
| 1 | `app.add_error_handler(_error_handler)` | All unhandled PTB handler exceptions |
| 2 | `loop.set_exception_handler(...)` | `asyncio.create_task()` and background task failures |
| 3 | `TelegramErrorHandler` on root logger | All `log.error()` / `log.critical()` calls |

All three layers call `error_reporter.report_exc()` which:
1. Classifies the error (ignored / warning / critical)
2. Formats a structured HTML report with traceback
3. Ships it to the `LOGS_ERRORS` Telegram channel (if configured)
4. Falls back to `print()` only if the Telegram send itself fails — never `log.error()` (which would cause infinite recursion)

---

## Flask Keepalive

`tcbot/alive.py` starts a Flask app in a daemon thread:

```python
# GET / → "OK"
app.run(host="0.0.0.0", port=cfg.port, debug=False, use_reloader=False)
```

Port is 8080 on Replit (set via `PORT` env var). Port is 5000 locally when `PORT` is not set.

The keepalive is required on Replit to prevent the container from sleeping.

---

## PTB Application Configuration

```python
Application.builder()
    .token(cfg.bot_token)
    .post_init(_post_init)
    .concurrent_updates(True)
    .connection_pool_size(8)
    .get_updates_connection_pool_size(4)
    .read_timeout(15)
    .write_timeout(15)
    .connect_timeout(10)
    .pool_timeout(5)
    .build()
```

`concurrent_updates=True` means each update is processed in its own asyncio task. PTB handles conversation locking automatically so ConversationHandlers for the same user/chat are still serialized.

---

## Related Documentation

- [Modules and service boundaries](modules.md)
- [Conversation flows and workflows](workflows.md)
- [Development workflow and onboarding](development.md)
- [AI agent instructions](../agents/CLAUDE.md)
- [Execution plan and bug tracker](../PLAN.md)
