# TCF Bot: Planning and Project State

This document tracks how TCF Bot currently runs, what is considered stable, and what should be improved next. Keep it practical: record current behavior, known risks, and validation commands rather than aspirational placeholders.

For user-facing overview, see [`README.md`](README.md). For contributor rules and style, see [`AGENTS.md`](AGENTS.md). For deployment notes, see [`replit.md`](replit.md). For developer documentation, see [`docs/README.md`](docs/README.md). For CI/CD automation details, see [`docs/workflows-guide.md`](docs/workflows-guide.md). For changelog of recent changes, see [`CHANGELOG.md`](CHANGELOG.md).

## Current Project State

| Area | Status |
|---|---|
| Runtime | Long-polling Telegram bot started with `uv run python -m tcbot`. |
| Python target | Python 3.12 project target (`pyproject.toml` requires `>=3.12`). |
| Bot framework | `python-telegram-bot` (plain, no `[job-queue]` extra), tracking the latest compatible release. |
| Database | MongoDB through Motor, connected during PTB `post_init`. |
| Cache | In-process `TTLCache` L1 + optional Redis L2 via `TwoLevelCache`. `hiredis` C extension required when Redis is active. Configured via `REDIS_URL`. |
| Scheduler | APScheduler **4.0.0a6** (`AsyncScheduler` + `MongoDBDataStore` + `CBORSerializer`); persistent moderation jobs survive restarts. The pinned alpha carries CVE-2026-31072 (no upstream patch); accepted and tracked risk, see Core Subsystem Design / Persistent Scheduler. |
| Health check | Flask app in `tcbot/alive.py`. `GET /` returns `OK`. `GET /health` returns JSON `{status, mongodb, redis, scheduler, ts}` with HTTP 200 (all ok) or HTTP 503 (degraded). Port from `PORT` env var (default `5000`). |
| Dependency management | `uv` with `uv.lock`; CI installs with frozen lockfile by default. |
| Formatting/linting | Ruff, configured in `pyproject.toml`. |
| Deployment notes | Local `config.env`, Docker Compose, and Replit/hosted environment variables are documented. |

## Runtime Flow

### Startup Sequence

```mermaid
flowchart TD
    Entry[uv run python -m tcbot] --> Init[tcbot.__init__]
    Init --> LoadEnv[Load environment and config.env]
    LoadEnv --> Config[Build Configs and cfg adapter]
    Config --> Main[tcbot.__main__.main]
    Main --> Logging[setup_logging]
    Main --> KeepAlive[start_keepalive on cfg.port]
    Main --> Builder[ApplicationBuilder - registers post_init callback]
    Builder --> Handlers[get_handlers - discover and import modules]
    Handlers --> AddHandlers[add_handler for each module + error handler]
    AddHandlers --> Polling[run_polling]
    Polling --> PostInit[post_init runs before polling loop]
    PostInit --> MongoDB[connect MongoDB + ensure_indexes + seed owner]
    PostInit --> Redis[connect Redis if REDIS_URL set - optional]
    PostInit --> APSched[start APScheduler MongoDBDataStore + CBORSerializer]
    PostInit --> Reporter[attach error_reporter + asyncio exception handler]
    Reporter --> Updates[accept Telegram updates]
```

### `post_init` Sequence

`_post_init(app)` runs after the PTB application is built and before polling starts:

1. Required env vars are parsed before startup; `BOT_TOKEN`, `MONGODB_URI`, and `OWNER_ID` must be present.
2. Enabled modules are imported during handler collection; import failures stop startup instead of silently skipping handlers.
3. `connect()` creates the Motor client and verifies MongoDB with `ping`.
4. `ensure_indexes()` creates required MongoDB indexes in parallel.
5. `ensure_initial_owner(cfg.initial_owner_id)` seeds the first owner when needed.
6. `redis_client.connect(cfg.redis_url)` connects to Redis when `REDIS_URL` is set. On failure, logs a warning and continues with in-memory cache only (Redis is optional).
7. `sched_mod.start()` starts APScheduler 4.x with `MongoDBDataStore` and `CBORSerializer`. Blocks until the scheduler background task is ready. Registers recurring warn-expiry and DB-cleanup jobs.
8. `error_reporter.attach(...)` stores the bot and error destination for async reports.
9. The asyncio loop exception handler is registered.

### Request Processing Pipeline

```mermaid
flowchart TD
    Update[Telegram update] --> GlobalLimit[group -1 global rate limiter]
    GlobalLimit --> ModuleHandlers[group 0 command and callback handlers]
    ModuleHandlers --> Helpers[Shared helpers and workflows]
    Helpers --> DbHelpers[Async database helpers]
    ModuleHandlers --> CacheUpdater[group 10 member cache updater]
```

## Architecture Summary

### Main Package Boundaries

| Path | Responsibility |
|---|---|
| `tcbot/__init__.py` | Environment parsing, `Configs`, and the global `cfg` adapter. |
| `tcbot/__main__.py` | Application startup, handler registration, MongoDB startup, polling, error handling. |
| `tcbot/alive.py` | Flask health-check server. |
| `tcbot/modules/` | Command modules and Telegram handlers. |
| `tcbot/modules/helper/` | Shared formatter, keyboard, decorator, target extraction, and role guard helpers. |
| `tcbot/modules/helper/workflows/` | ConversationHandler flows, all named `*_flow.py`. |
| `tcbot/database/` | Async MongoDB access helpers and document/type definitions. |
| `tcbot/utils/` | Logging, bounded fan-out dispatch, prefix filters, datetime helpers, error reporting. |

### Module Discovery

`tcbot/modules/__init__.py` discovers top-level `*.py` files in `tcbot/modules/`, excludes `__init__.py`, applies the optional `MODULES_LOAD` allowlist and `MODULES_NO_LOAD` denylist, imports active modules, and collects their `__handlers__` lists. If any enabled module fails to import, startup now exits with the failing module names so a partially registered bot is not deployed.

### Database Layer

All database operations are async and should go through helper modules in `tcbot/database/`.

Current collection/domain owners include:

| Collection/domain | Helper |
|---|---|
| Federation bans | `bans_db.py` |
| Connected and pending groups | `groups_db.py` |
| Member profile cache | `users_cache.py` |
| Owners/admins + dev/tester roles | `users_roles.py` |
| Warnings | `warns_db.py` |
| Kicks | `kicks_db.py` |
| Mutes | `mutes_db.py` |
| Promotion requests | `queues_db.py` |
| MongoDB client/indexes | `mongos.py` |
| In-memory + Redis caches | `cache.py` |
| Redis client and connection pool | `redis_client.py` |
| Persistent moderation scheduler | `scheduler.py` |
| Typed document shapes | `documents.py` |
| Domain primitive types | `types.py` |

### Error Handling

| Layer | Location | Purpose |
|---|---|---|
| PTB error handler | `app.add_error_handler(_error_handler)` | Reports unhandled handler exceptions. |
| Asyncio exception handler | `loop.set_exception_handler(...)` | Reports background task failures. |
| Logging integration | `tcbot/utils/error_reporter.py` | Sends formatted error details to the configured destination. |

## Core Subsystem Design

This section records how the three load-bearing subsystems (MongoDB access, the
caching layer, and the persistent scheduler) are built today, the tuning knobs
that exist, and the recommended direction for each. It is the canonical design
reference for these subsystems; keep it in sync when the code changes.

### Data Store: MongoDB via Motor

**Current design** (`tcbot/database/mongos.py`):

- One shared `AsyncIOMotorClient` is created in `connect()` and stored as the
  module global `_db`. All access goes through `db()` and `col(name)`; no module
  opens its own client. `connect()` verifies the link with a `ping` before
  startup proceeds.
- Connection pool and timeout parameters are centralised as module constants:

  | Parameter | Value | Purpose |
  |---|---|---|
  | `serverSelectionTimeoutMS` | 10000 | Fail fast when no node is reachable. |
  | `connectTimeoutMS` | 10000 | Cap the initial TCP/TLS handshake. |
  | `socketTimeoutMS` | 45000 | Cap a single operation; long enough for slow aggregations. |
  | `maxPoolSize` | 20 | Upper bound on concurrent sockets for one bot instance. |
  | `minPoolSize` | 2 | Keep warm sockets ready. |
  | `maxIdleTimeMS` | 60000 | Recycle idle sockets. |
  | `heartbeatFrequencyMS` | 30000 | Topology monitoring cadence. |
  | `compressors` | `["zlib"]` | Wire compression. |
  | `retryWrites` / `retryReads` | True | Transparent one-time retry on transient errors. |

- `ensure_indexes()` creates roughly two dozen indexes in parallel with
  `asyncio.gather(..., return_exceptions=True)`. Individual index failures are
  logged and counted (`X/Y succeeded`) rather than silently dropped. Several
  indexes are deliberately covered: for example the
  `(user_id, first_name, username)` index on `member_cache` serves the batch
  `$in` projections in `users_cache` without touching documents.
- `_patch_dns_if_needed()` installs a fallback resolver (8.8.8.8 / 8.8.4.4) when
  `/etc/resolv.conf` is absent, so `mongodb+srv://` works on Termux/Android and
  similar restricted hosts.
- `make_short_id()` issues URL-safe, cryptographically random record IDs.

**Recommendations:**

- Keep every new collection's indexes in `ensure_indexes()` and match query
  shapes to an existing index; consult the `mongodb-query-optimizer` guidance
  before adding a query.
- Operational hardening is the main lever for the scheduler CVE below: use a
  least-privilege MongoDB user scoped to this database only, restrict network
  access with an Atlas IP allowlist (or a firewall for self-hosted), and never
  let `MONGODB_URI` reach git, logs, or screenshots.
- Consider replacing the weekly `member_cache` cleanup job with a MongoDB TTL
  index on `last_updated` (`expireAfterSeconds` = 90 days). The server would then
  expire stale rows on its own, removing one persistent APScheduler job and the
  weekly `delete_many` sweep. Optional simplification, recorded as a future idea.

### Caching: L1 in-process / L2 Redis / L3 MongoDB

**Current design** (`tcbot/database/cache.py`):

The read hot-path is a three-tier lookup implemented by
`TwoLevelCache.get_or_fetch(key, fetch)`:

| Tier | Backing | Cost | Behaviour |
|---|---|---|---|
| L1 | in-process `cachetools.TTLCache` | sub-microsecond, no I/O | LRU + TTL eviction, bounded by `maxsize`. |
| L2 | Redis (optional) | one round-trip | Shared across runs/processes; JSON-encoded values. |
| L3 | the `fetch()` coroutine | a MongoDB query | Source of truth; the result back-fills L1 (and L2). |

- Writes and invalidations (`put` / `invalidate`) update L1 synchronously and
  fire-and-forget the matching Redis write/delete. Background Redis tasks are
  held in a strong-reference set so they are not garbage-collected mid-flight.
- Redis is fully optional. When `REDIS_URL` is unset or Redis is unreachable,
  all Redis operations are skipped and the cache behaves exactly like a pure L1
  `TTLCache`. Redis errors are logged at debug level and never propagate.
- The shared singletons and their tuned TTLs:

  | Cache | L1 TTL | L2 TTL | maxsize | Invalidated by |
  |---|---|---|---|---|
  | `effective_role_cache` | 60s | 90s | 2048 | every role write |
  | `connected_cache` | 120s | 180s | 512 | group add/deactivate |
  | `active_groups_cache` | 30s | 45s | 4 | group add/deactivate |
  | `owner_id_cache` | 300s | 360s | 4 | set_owner / initial seed |
  | `user_mention_cache` | 300s | 600s | 4096 | upsert_user |

  L2 TTLs are deliberately a little longer than L1 so Redis can still serve a
  warm value just after an L1 entry expires.

**Recommendations:**

- L1 invalidation is per-process. The bot runs as a single long-polling instance
  (the `tcf-bot-runner` concurrency group guarantees exactly one poller), so this
  is correct today. If the bot is ever scaled past one instance, an L1 entry
  invalidated on instance A stays warm on instance B until its `memory_ttl`
  expires; design a Redis pub/sub invalidation channel before scaling out.
- `get_or_fetch` takes no per-key lock, so several concurrent misses on the same
  key each run `fetch()` (a cache stampede). On a single event loop with the
  current low contention this is acceptable; revisit only if profiling shows a
  hot key.
- Cached value types must stay JSON-round-trippable because Redis stores JSON.
  Tuples return as lists; keep the existing list-typed annotations and the
  caller-side casts.

### Persistent Scheduler: APScheduler 4.x

**Current design** (`tcbot/database/scheduler.py`):

- Uses `AsyncScheduler` with `MongoDBDataStore` + `CBORSerializer`, so schedules
  and job state live in MongoDB and survive bot restarts.
- The whole `async with AsyncScheduler()` lifecycle runs inside one dedicated
  asyncio task (`tcbot.scheduler`), because AnyIO requires the cancel scope to be
  entered and exited in the same task. `start()` blocks on a ready `Event`;
  `stop()` sets a stop `Event` and waits up to 10s for a clean exit.
- Jobs are module-level callables so their import paths can be serialised and
  re-bound after a restart. `ConflictPolicy.replace` plus stable IDs keep
  recurring schedules from duplicating across restarts.

  | Job | Trigger | Notes |
  |---|---|---|
  | `_expire_old_warns` | every 24h | Only when `WARN_EXPIRY_DAYS > 0`; otherwise the schedule is removed. |
  | `_execute_scheduled_unban` | one-off `DateTrigger` | Flips the ban record `is_active = False` at expiry. |

  `member_cache` cleanup is now handled by a MongoDB TTL index on `last_updated`
  (`expireAfterSeconds=7776000`, 90 days) created in `mongos.ensure_indexes()`.
  The former `_cleanup_old_records` weekly APScheduler job has been retired;
  it remains as a no-op migration shim so any persisted schedule can be deserialised,
  and is actively removed from the APScheduler datastore on first startup.

- Note on scheduled unban: the real Telegram unban is enforced natively by the
  timed `restrict_chat_member` / `ban_chat_member` `until_date` set at ban time.
  The scheduled job only deactivates the DB record for history hygiene; it is not
  what actually frees the user.

**Security: CVE-2026-31072 (GHSA-9cfw-f3f9-7mm7), accepted and tracked risk**

- Advisory: APScheduler's `JSONSerializer` and `CBORSerializer` are vulnerable to
  RCE via insecure deserialization. `unmarshal_object` can be coerced into
  instantiating an arbitrary class and calling `__setstate__` on it when it
  deserialises a crafted JSON/CBOR payload. CVSS 9.8.
- Affected range: `>= 4.0.0a1, <= 4.0.0a6`. The project is pinned to `4.0.0a6`
  in `uv.lock`. There is no patched release: every published 4.x is a vulnerable
  alpha, and the 3.x line is a different API with no `AsyncScheduler` /
  `MongoDBDataStore`. `first_patched_version` is null.
- Reachability in this deployment is low. The serializer only ever deserialises
  schedule documents that the bot itself wrote into its own private MongoDB data
  store, and those documents reference fixed module-level callables with
  primitive kwargs (`ban_id`, `user_id`, `warn_expiry_days`). No Telegram-facing
  code path lets a user write arbitrary bytes into the `apscheduler` collections.
  Exploitation therefore requires an attacker who already holds write access to
  the bot's MongoDB (a leaked `MONGODB_URI`, an exposed or unauthenticated
  instance, or a shared cluster). Under a private, authenticated, IP-allowlisted
  MongoDB this is defense-in-depth, not a remotely triggerable hole.
- Decision: accept the risk for now. There is nothing to upgrade to, and a
  downgrade would remove the persistence the scheduler depends on.
- Mitigations (operational, see the MongoDB recommendations above): private,
  least-privilege, IP-allowlisted MongoDB; secret hygiene for `MONGODB_URI`;
  rotate the URI immediately on any suspected leak.
- Watch: re-check the alert and upgrade as soon as APScheduler ships a fixed
  release. Quick check:

  ```bash
  gh api repos/D1ZZY4/tcbot/dependabot/alerts/2 --jq '.security_vulnerability.first_patched_version'
  ```

- Optional future hardening: the only one-off job is the DB-side unban, which is
  redundant with Telegram's native timed unban. Recomputing `is_active` from the
  stored expiry on read (or a periodic sweep), plus a MongoDB TTL index for the
  member_cache cleanup, would let both the one-off and weekly scheduler jobs
  retire and shrink the deserialisation surface. Recorded as a direction, not a
  mandate.

## Role System Summary

Role hierarchy:

1. Founder
2. Admin
3. Developer
4. Tester

Important rules:

- Use canonical role helpers from `tcbot.database.users_roles` and `tcbot.modules.helper.decorators.resolve_and_check`.
- Do not duplicate manual role-check chains in handlers.
- Ban and kick flows must auto-demote targets that currently hold a federation role.
- Promotion and demotion workflows should preserve auditability through logs and queue records.

## Conversation Flow Summary

Conversation flows live in `tcbot/modules/helper/workflows/` and use `ConversationHandler` where needed.

Primary flows:

| Flow | Purpose |
|---|---|
| `ban_flow.py` | Ban proof collection, album buffering, and federation ban execution. |
| `appeal_flow.py` | Private appeal submission and staff decision handling. |
| `connected_flow.py` | Group join approval and connection checks. |
| `reason_flow.py` | Shared reason/proof steps for moderation actions. |
| `proof_flow.py` | Proof upload helpers and prompts. |
| `kicking_flow.py`, `muting_flow.py`, `warning_flow.py`, `unban_flow.py` | Action-specific moderation workflows. |
| `promote_flow.py` | Role promotion execution helpers. |
| `stats_flow.py` | Unified `Stats` class covering overview, staff roster, users, chats, bans, and search. |

For detailed behavior, see `docs/workflows/workflows.md`.

## Development and Validation Commands

Install dependencies:

```bash
uv sync
```

Run the bot:

```bash
uv run python -m tcbot
```

Format and lint:

```bash
uv run ruff format .
uv run ruff check --fix .
```

Run local bot + MongoDB:

```bash
docker-compose up --build
```

## Improvement Strategy

Priorities, in order:

1. **Correctness and safety:** preserve federation moderation behavior, secrets safety, and database compatibility.
2. **Clear module boundaries:** handlers call helpers; database writes stay in `tcbot/database/`; shared flows stay in `workflows/`.
3. **Operational visibility:** errors and important moderation events should be logged to configured destinations.
4. **Performance:** use bounded fan-out for group-wide operations and avoid sequential I/O where safe.

## Current Priority Backlog

> The backlog below was re-verified line by line against the source tree on
> 2026-06-01. Each prior entry was checked against the actual code rather than
> trusted from a previous review pass. The disposition of every prior claim is
> recorded under "Backlog Review" so the audit trail stays clear.

## Code Review Findings

Use this section to keep code review findings in one consistent place. It applies
to anyone reviewing this codebase. After a review, add each finding as a row in the
table for its priority tier, where P1 is the highest and P5 is the lowest.
Confirmed and prioritized items move up into the
[Current Priority Backlog](#current-priority-backlog) above. Cleared items are set
to `Dismissed` with the reason written in the Evidence column. The italic rows are
placeholders that show the expected format, so replace them and do not leave them
in.

### How to record a finding

- One finding per row, specific and self-contained.
- **Location** must be a real `file.py:line` you actually opened, never a guess.
- **Evidence** must quote the relevant code or describe the behavior you observed
  that proves the finding is real. A finding with no evidence counts as unverified.
- **Verify first.** Open the cited file and confirm the issue is not already
  handled before listing it. In the 2026-06-01 review, several findings flagged as
  critical turned out to be already implemented in the code.
- **Do not overstate severity.** Already-validated input, idiomatic framework
  usage, and marginal micro-optimizations are not P1 or P2.
- **Status** uses the values below. Use `Resolved` only when a fix has landed and
  validation passes. Use `Dismissed` (with a reason) when verification shows the finding
  is not a real issue.

**Status values:**

- `Open`: logged, not started.
- `Verified`: confirmed against the code.
- `In Progress`: being worked on.
- `Resolved`: fixed and validated.
- `Dismissed`: checked and not a real issue, with the reason in Evidence.

**Priority tiers:**

- **P1 (Critical):** security holes, data loss, crashes, or broken core moderation; fix before the next release.
- **P2 (High):** incorrect behavior in critical logic such as auth and federation actions.
- **P3 (Medium):** maintainability and non-hot-path performance.
- **P4 (Low):** documentation gaps, minor cleanups, and naming.
- **P5 (Optional / Future):** speculative or nice-to-have ideas; gather evidence before promoting them.

### P1 (Critical)

| # | Finding | Location (`file.py:line`) | Evidence (code quote / observed behavior) | Proposed Fix | Status |
|--|--|--|--|--|--|
| 1 | `_paginate`, `_nav_row`, `_date` undefined at runtime in `stats_flow.py` | `tcbot/modules/helper/workflows/stats_flow.py:1` | All twelve call sites used private names (`_paginate`, `_nav_row`, `_date`) that were never defined in the module; calling any Stats drill-down raised `NameError` immediately | Replace all call sites with `paginate(..., _PAGE_SIZE)`, `nav_row(...)`, `date_or_unknown(...)` imported from `tcbot.utils.pagination` | `Resolved` |
| 2 | `_paginate`, `_nav_row`, `_date` undefined at runtime in `check_flow.py` | `tcbot/modules/helper/workflows/check_flow.py:1` | Same root cause as stats_flow: twelve call sites used stale private names leftover from before pagination was extracted to utils; any Check drill-down raised `NameError` | Add `from tcbot.utils.pagination import date_or_unknown, nav_row, paginate` and replace all twelve call sites | `Resolved` |
| 3 | `_kb` undefined at runtime in `tcbot/modules/groups.py` | `tcbot/modules/groups.py:85,103` | `_kb(False)` and `_kb(detailed)` called but never defined; `/tcgroups` and Detail/Simple toggle both raised `NameError` immediately | Imported `tcgroups_kb` from `tcbot.modules.helper.keyboards` and replaced both `_kb(...)` call sites | `Resolved` |
| 4 | APScheduler 4.0.0a6 RCE via insecure deserialization (CVE-2026-31072 / GHSA-9cfw-f3f9-7mm7) | `tcbot/database/scheduler.py:35`, `uv.lock` (apscheduler 4.0.0a6) | CVSS 9.8. `unmarshal_object` instantiates an arbitrary class and calls `__setstate__` on a crafted CBOR/JSON payload. No patched release exists (all published 4.x are affected alphas; `first_patched` is null). Reachability is gated by MongoDB write access: only the bot writes fixed module-level callables with primitive kwargs, so it is not triggerable from Telegram. Full analysis under Core Subsystem Design / Persistent Scheduler. | Upgrade as soon as upstream ships a fix; until then mitigate operationally (private, least-privilege, IP-allowlisted MongoDB; `MONGODB_URI` secret hygiene). Accepted/tracked risk. | `Open` |

### P2 (High)

| # | Finding | Location (`file.py:line`) | Evidence (code quote / observed behavior) | Proposed Fix | Status |
|--|--|--|--|--|--|
| 1 | Layer 3 asyncio exception handler scheduled a fire-and-forget report task without a strong reference | `tcbot/__main__.py:150` | `lp.create_task(error_reporter.report_exc(...))` discarded the returned task; Python may garbage collect the task before it runs, dropping the error report from the last-resort handler | Store each task in a module-level `set` and register a `discard` done-callback (mirrors `logger._tg_tasks`). RUF006 missed it because the task is created through the `lp` parameter, which ruff cannot statically identify as an event loop | `Resolved` |

### P3 (Medium)

| # | Finding | Location (`file.py:line`) | Evidence (code quote / observed behavior) | Proposed Fix | Status |
|--|--|--|--|--|--|
| 1 | `uv run ruff` documented throughout `.agents/` but silently failed on Replit | `.agents/STYLE-CODE.md:17`, `.agents/RUFF.md:53` | `uv run ruff format .` exited with code 1 because ruff was in `[project.optional-dependencies.dev]`, which `uv run` does not install by default | Moved ruff to `[dependency-groups] dev = ["ruff"]` in `pyproject.toml`; `uv sync` now installs it automatically; `uv run ruff check .` and `uv run ruff format .` both pass clean | `Resolved` |

### P4 (Low)

| # | Finding | Location (`file.py:line`) | Evidence (code quote / observed behavior) | Proposed Fix | Status |
|--|--|--|--|--|--|
| 1 | `performance.yml` benchmark imported non-existent module `users_db` | `.github/workflows/performance.yml:49,68` | `from tcbot.database import users_db`: module was split and removed; correct module is `users_cache`; calls to `users_db.get_first_names_batch` and `users_db.get_mention_data_batch` would fail at import time | Replace both imports with `users_cache`; rename all call sites | `Resolved` |
| 2 | `performance.yml` Compare-baseline script used `os.environ` without `import os` | `.github/workflows/performance.yml:207` | Python inline script imported only `sys`; `os.environ["GITHUB_OUTPUT"]` on regression would raise `NameError: os is not defined` | Add `import os` at top of script | `Resolved` |
| 3 | `auto-fix.yml` schedule cron `0 4 * * 1` annotated as "02:00 UTC" | `.github/workflows/auto-fix.yml:10` | Comment read `# Weekly Monday 02:00 UTC` but cron fires at 04:00 UTC; same wrong time propagated to `README.md` and two places in `docs/workflows-guide.md` | Fix comment in YAML; update four documentation references | `Resolved` |
| 4 | `docs/workflows-guide.md` and `README.md` described run-bot.yml as "Manual deployment" | `docs/workflows-guide.md:251`, `README.md:255` | `run-bot.yml` has `schedule: cron: "0 */4 * * *"`: it runs every 4 hours automatically; "Manual dispatch only" was wrong | Update overview line, section body, and README entry | `Resolved` |
| 5 | `config.env.example` claimed `PORT=auto` lets system pick a free port | `config.env.example:31` | `parse_port()` returns 5000 for "auto"; no OS port discovery exists | Rewrite PORT comment to describe actual fallback behavior | `Resolved` |
| 6 | `config.env.example` claimed `PROOFS/LOGS/LOGS_ERRORS/APPEALS=auto` creates forum threads | `config.env.example:57,65,73,81` | No forum-thread auto-creation code exists anywhere in `tcbot/`; these comments described non-existent functionality | Remove the four "auto" comment blocks; replace with accurate format guidance | `Resolved` |
| 7 | 12 public functions had no docstrings | multiple files | `bold()`, `italic()`, `code()`, `link()`, `esc()`, `on_groups_details()`, `on_groups_simple()`, `on_help_menu()`, `on_helpc_main()`, `appeal_deep_link()`, `on_menu_groups()`, `on_menu_groups_simple()` had empty docstring slots | Add one-line docstrings to each | `Resolved` |

### P5 (Optional / Future)

| # | Finding | Location (`file.py:line`) | Evidence (code quote / observed behavior) | Proposed Fix | Status |
|--|--|--|--|--|--|
| 1 | `member_cache` batch queries could benefit from a covered composite index | `tcbot/database/mongos.py:1` | `get_first_names_batch` issues `$in` on `user_id` with a `first_name` projection; existing `user_id` index is not covering | `{user_id: 1, first_name: 1, username: 1}` index added to `ensure_indexes()` on 2026-06-02; batch `$in` projections are now covered queries. | `Resolved` |

### Improvements

Evidence-grounded improvement ideas. Same format as the priority tiers; these are
enhancements rather than defects, so they stay here until promoted into a backlog
item when work begins.

| # | Finding | Location (`file.py:line`) | Evidence (code quote / observed behavior) | Proposed Fix | Status |
|--|--|--|--|--|--|
| 1 | Health check is not meaningful for 24/7 monitoring | `tcbot/alive.py:24` | `GET /` returned the literal `OK` regardless of MongoDB or polling state; silently dead bot looked healthy | Added `GET /health` endpoint: returns JSON with `mongodb`, `redis`, `scheduler` subsystem states, `status` (ok/degraded), and `ts` (ISO timestamp); returns HTTP 503 when degraded. `mongos.is_connected()` and `sched_mod.is_ready()` added as public state-readers | `Resolved` |
| 2 | No documented backup for irreplaceable federation data | `tcbot/database/bans_db.py:1`, `tcbot/database/users_roles.py:1`, `tcbot/database/groups_db.py:1` | Federation bans, roles (`tc_owners`/`tc_admins`/`tc_roles`), and connected groups cannot be reconstructed; the P1 tier counts data loss as critical, yet no backup procedure exists | Enable Atlas continuous or snapshot backups (or a `mongodump` cron for self-hosted) and write a short restore runbook; also bounds the blast radius of the scheduler CVE | `Open` |
| 3 | Persistent-scheduler surface is larger than it needs to be | `tcbot/database/scheduler.py:106`, `tcbot/database/scheduler.py:92` | `_execute_scheduled_unban` only flips `is_active = False` (the real unban is enforced natively by Telegram's `until_date`); `_cleanup_old_records` was a single weekly `delete_many` on an age threshold | Replaced the weekly cleanup with a MongoDB TTL index on `member_cache.last_updated` (`expireAfterSeconds=7776000`, 90 days) in `mongos.ensure_indexes()`; the `_cleanup_old_records` job retired to a no-op migration shim; stale schedule removed from APScheduler datastore on first startup after upgrade | `Resolved` |
| 4 | L1 cache invalidation is per-process (blocks scaling out) | `tcbot/database/cache.py:147` | `invalidate` updates only the local in-process L1; this is correct only because the `tcf-bot-runner` concurrency group guarantees a single poller | Add a Redis pub/sub invalidation channel so an L1 entry dropped on one instance is dropped everywhere, before ever running more than one instance; not needed while single-instance | `Open` |
| 5 | Dependency upgrades are unguarded except by the import check | `pyproject.toml:6`, `.github/workflows/dependency-update.yml:1` | Top-level dependencies were unversioned and floated to latest via the weekly `uv lock --upgrade`; APScheduler used `>=4.0.0a1` which could float to any vulnerable alpha | Pinned APScheduler to `==4.0.0a6` in `pyproject.toml`; prevents blind upgrade to another vulnerable alpha until upstream ships a patched release | `Resolved` |

## Maintenance Rules

- Do not commit real secrets or private chat IDs.
- Do not edit `config.env` for normal documentation or code changes.
- Do not add dependencies manually to a requirements file; use `uv` and `pyproject.toml`.
- Keep database schema changes backward-compatible unless a migration plan is included.
- Keep bot messages HTML-only and escape user-provided text through formatter helpers.
- Keep conversation files named `*_flow.py`.

## Recent Documentation Baseline

This documentation pass updates the root Markdown files to reflect the current project stack, runtime flow, configuration model, and deployment guidance:

- `AGENTS.md`
- `README.md`
- `PLAN.md`
- `replit.md`