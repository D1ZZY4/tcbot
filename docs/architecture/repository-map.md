# Repository map

This page describes the physical layout of the repository, what each package
owns, and how the process comes up. It is the orientation page for new
contributors. For the runtime flow drawn as diagrams, see
[the system spine](../pipelines/banning.md).

## Top-level layout

```text
<project root>/
├── tcbot/                    Application package
├── alembic/                  Alembic migration scripts and revisions
├── i18n/                     TOML translation catalogs (en-US is the source)
├── tests/                    Pytest suite
├── scripts/                  One-shot operator tools
├── .github/workflows/        CI and deployment workflows
├── .agents/rules/            Agent and contributor rules
├── docs/                     This documentation set
├── config.env.example        Environment variable template
├── docker-compose.yml        Local bot, PostgreSQL, and Redis stack
├── Dockerfile                Container image definition
├── pyproject.toml            Dependencies and tool configuration
├── uv.lock                   Locked dependency graph
├── pyrightconfig.json        Static type checker configuration
└── AGENTS.md                 Top-level repository guide
```

## The `tcbot/` package

| Path | Responsibility |
|---|---|
| `tcbot/__init__.py` | Environment parsing and the immutable `Configs` model. `cfg` is built on first access. |
| `tcbot/__main__.py` | Application lifecycle, builder, handler registration, webhook or polling transport, and shutdown drains. |
| `tcbot/alive.py` | Flask keep-alive server, `/health`, `/metrics`, and the `/webhook` receiver. |
| `tcbot/error_reporter.py` | Error classification, scrubbing, deduplication, throttling, and shipping to the configured error destination. |
| `tcbot/enforcement_worker.py` | Deliver queued `apply`, `revoke`, and `reconcile` enforcement runs to Telegram. |
| `tcbot/notification_worker.py` | Retry review-card edits from the durable notification outbox. |
| `tcbot/database/` | PostgreSQL schemas, tables, helpers, migrations, cache, scheduler, and MTProto store. |
| `tcbot/modules/` | Telegram command, callback, and event modules plus the `helper/` subpackage. |
| `tcbot/utils/` | Cross-cutting runtime utilities. |

### Database package

`tcbot/database/__init__.py` imports submodules lazily so schema and migration
tools can read table definitions without loading the whole application. The
main areas are:

- `base/`: SQLAlchemy table and column definitions grouped by domain.
- `schema/`: SQL views, functions, triggers, policies, and seed data, applied
  in that order by `schema/loader.py`.
- `cache/`: the two-level cache, tagged JSON codec, Redis boundary, and shared
  singletons.
- `scheduler/`: APScheduler task wiring and the scheduled maintenance jobs.
- `bans_db/` and `rules_db/`: domain packages split into focused submodules
  with a thin re-exporting `__init__.py`.
- `engine.py`: the async engine, session boundary, and `db_call` /
  `run_transaction` guard.
- `*_db.py` helpers: one module per domain, such as `groups_db.py`,
  `warns_db.py`, `users_roles.py`, and `enforcement_db.py`.

See [the database layer](database.md).

### Modules and helpers

`tcbot/modules/*.py` are the command modules. `tcbot/modules/__init__.py`
discovers them, applies `MODULES_LOAD` and `MODULES_NO_LOAD`, and collects each
module's `__handlers__` list. `helper/` holds shared code and never registers
handlers directly.

The helper subpackage is split by responsibility:

- `decorators/`: authorization and throttle decorators.
- `guards.py`, `identity.py`, `targets.py`, `extraction/`: who may act, on whom.
- `scope.py`, `locale.py`: per-conversation payload scope and locale resolution.
- `pipelines/`: `*_flow.py` ConversationHandler factories and their steps.
- `buttons/`: all inline keyboard builders.
- `messages/`: the rich-message transport, formatters, panels, links, and
  audit-log builders.

See [modules](modules.md) and [the helper package](helpers.md).

## Startup sequence

`main()` in `tcbot/__main__.py` owns startup:

1. Set up logging from `cfg.log_level` and initialize Sentry when a DSN is
   configured.
2. Start the Flask keep-alive server on `cfg.bind_host` and `cfg.port`. The
   port is probed first so a bind failure fails fast.
3. Build the PTB `Application` with shared HTTP timeouts, the `AIORateLimiter`,
   and a keyed update processor that serializes updates per `(chat, user)`.
4. Register handlers: the global rate-limit `TypeHandler` at group `-1`, all
   module handlers, the member-cache harvester at group `10`, and the error
   handler.
5. Run either webhook mode or polling mode. Webhook mode calls
   `set_webhook`, verifies the registered URL, and wires the Flask receiver.
6. `post_init` connects PostgreSQL, applies migrations, seeds the initial
   Owner, registers infrastructure destinations, connects Redis and MTProto,
   attaches the error reporter, starts the scheduler, and warms hot caches.

Shutdown drains Bot-dependent work in `post_stop` while the Bot client is
still available, then closes external clients in `post_shutdown`.

## Service boundaries

| Service | Owner | Notes |
|---|---|---|
| Telegram transport | PTB `Application` | Webhook is the production path. Polling is the local fallback. |
| HTTP health and webhook | Flask in a daemon thread | Updates cross into the asyncio loop through `asyncio.run_coroutine_threadsafe`. |
| PostgreSQL | `database/engine.py` | Every call runs through `db_call` with a circuit breaker and timeout. |
| Cache | `database/cache/` | In-memory L1 always, optional Redis L2. |
| Scheduling | `database/scheduler/` | APScheduler with a SQLAlchemy job store; optional pg_cron ownership for database-only jobs. |
| MTProto | `database/mtproto.py` | Bot-token identity lookups with PostgreSQL-backed session storage. |

## Conventions

- Source files stay at or below 1,000 lines. Oversized modules are split into
  a same-named package with a re-exporting `__init__.py`.
- Python 3.14 syntax, four-space indentation, and Ruff formatting.
- Configuration is parsed once in `tcbot/__init__.py`.
- All user-facing wording lives in `i18n/<locale>/*.toml`.

Validation commands are listed in the [setup guide](../getting-started/setup.md).
