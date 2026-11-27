# Architecture overview

This page describes the physical layout of the repository, what each package
owns, and how the process comes up. The flows drawn as diagrams are in
[the system spine](../flows/system.md).

## Top-level layout

```text
<project root>/
├── tcbot/                  Application package
├── alembic/                Alembic migration scripts and revisions
├── about/                  Bundled About source documents
├── acknowledge/            Bundled self-acknowledgement source document
├── rules/                  Bundled rule documents for scripts/seed_rules.py
├── i18n/                   TOML translation catalogs (en-US is the source)
├── tests/                  Pytest suite
├── scripts/                One-shot operator tools
├── .github/workflows/      CI and deployment workflows
├── .agents/rules/          Agent and contributor rules
├── docs/                   This documentation set
├── config.env.example      Environment variable template
├── docker-compose.yml      Local bot, PostgreSQL, and Redis stack
├── Dockerfile              Container image definition
├── pyproject.toml          Dependencies and tool configuration
├── uv.lock                 Locked dependency graph
├── pyrightconfig.json      Static type checker configuration
└── AGENTS.md               Top-level repository guide
```

## The `tcbot/` package

| Path | Responsibility |
|---|---|
| `tcbot/__init__.py` | Environment parsing and the immutable `Configs` model. `cfg` is built on first access. |
| `tcbot/__main__.py` | Application lifecycle, error reporting, handler registration, Kurigram polling transport, and shutdown drains. |
| `tcbot/alive.py` | Flask keep-alive server with `/health` and `/metrics`. |
| `tcbot/modules/helper/pipelines/errors/` | Error classification (`classify.py`), exceptions (`exceptions.py`), redaction (`redaction.py`), and report delivery (`report.py`). |
| `tcbot/modules/helper/pipelines/moderation_enforcement.py` | Deliver queued `apply`, `revoke`, and `reconcile` runs to Telegram. |
| `tcbot/notification_worker.py` | Retry review-card edits from the durable notification outbox. |
| `tcbot/database/` | PostgreSQL schemas, tables, helpers, migrations, cache, scheduler, and MTProto store. |
| `tcbot/modules/` | Telegram command, callback, and event modules plus the `helper/` subpackage. |
| `tcbot/utils/` | Cross-cutting runtime utilities. |

See [Database](database.md), [Security](security.md), and [Runtime](runtime.md).

## Startup sequence

`main()` in `tcbot/__main__.py` owns startup:

1. Set up logging and initialize Sentry when a DSN is configured.
2. Start the Flask keep-alive server on `cfg.bind_host` and `cfg.port`. The port
   is probed first so a bind failure fails fast.
3. Create the single Kurigram client (bot token and API credentials) and discover
   the active modules.
4. Register the member-cache harvester at group `-1`, all module handlers, a
   last-responder callback handler at group `20`, and the error handler.
   Per-handler `ratelimiter()` decorators provide throttling.
5. `init_shared_subsystems()` connects PostgreSQL, applies migrations, seeds the
   Owner, registers infrastructure destinations, connects Redis, starts the
   Kurigram session, attaches the error reporter, starts the scheduler, and warms
   hot caches.
6. Enter the native long-polling idle loop. There is one transport in every
   environment.

Shutdown runs `_shutdown_subsystems()`, which stops the scheduler and drains
proof uploads, identity refreshes and error reports before closing the client and
every external connection.

## Module discovery and registration

`tcbot/modules/__init__.py` is the single owner of module discovery. It finds
every `*.py` file in `tcbot/modules/` except `__init__.py`, plus every
subdirectory with an `__init__.py` except `helper` and `__pycache__`. Names are
sorted so registration order is deterministic. `MODULES_LOAD` and
`MODULES_NO_LOAD` are validated against the discovered set; an invalid name
exits startup with an error. Each module exposes `__handlers__` and, where it
describes itself, `get_help(locale)`.

`register_handlers()` attaches, in order, the member-cache harvester, the
collected module handlers, and the error handler.
Most module handlers sit in Kurigram group `0`, where the dispatcher runs the
first matching handler. A handler that does not own an update must hand it on
with `ContinuePropagation` instead of returning normally; a later group does not
suppress earlier groups. The unowned-callback responder sits in group `20`, so it
runs only after every module handler has declined the tap. Commands are matched by
`build_prefixed_filters()` against all configured prefixes. See
[Commands](../reference/commands.md) for the ownership table.

## Handler anatomy

Handlers are small orchestration functions. A typical handler guards
`effective_message`, `effective_user`, and `effective_chat`; resolves the locale
once with `locale_for_update`; delegates authorization to decorators and guards;
delegates persistence to `*_db.py` helpers; delegates multi-step work to a
domain-named pipeline module; and sends replies through the `messages` helpers
(`reply_rich`, defined in `rich/reply_msg.py`).

Decorator order is fixed: `ratelimiter()` outermost, the required authorization
guard second, and `log_execution` innermost. Message-event handlers are exempt
from per-handler rate limits. Callback-query handlers answer the query before
visible work. See [Security](security.md) for the tier and guard contracts.

## Helper package

`tcbot/modules/helper/` owns shared code and never registers handlers itself:

| Path | Responsibility |
|---|---|
| `decorators/` | Rate-limit and authorization decorators plus execution logging. |
| `guards.py`, `identity.py`, `targets.py`, `extraction/` | Who may act, on whom, and how a target is resolved. |
| `locale.py`, `scope.py` | Per-update locale and per-conversation payload scope. |
| `ban_info.py`, `replies` via `messages/replies.py` | Shared ban details and localized replies. |
| `pipelines/` | Domain-named `*_executor.py`, `*_conversation.py`, `*_steps.py`, `*_panels.py`, or plain ConversationHandler factories and their steps. |
| `buttons/` | Every inline keyboard builder. |
| `messages/` | Safe edits, channel delivery, panels, replies, and audit-log builders; re-exports rich transports for stable dotted paths. |
| `rich/` | Rich HTML primitives, links and mentions, buttons, block conversion, media, and the send, reply, edit, and forward transports. |

## Runtime utilities

`tcbot/utils/` owns cross-cutting behaviour without domain rules. The main
modules are `i18n.py`, `dispatch.py`, `circuit_breaker.py`, `transport.py`,
`time_and_date.py`, `prefixes.py`, `logger.py`, `metrics.py`, `tasks.py`,
`update_processor.py`, `pagination.py`, and `secrets.py`. Error reporting lives
in `tcbot/modules/helper/pipelines/errors/`. See [Runtime](runtime.md).

## Service boundaries

| Service | Owner | Notes |
|---|---|---|
| Telegram transport | Single Kurigram client | Native long polling is the only path. |
| HTTP health | Flask in a daemon thread | Serves only `/`, `/health` and `/metrics`; it never receives Telegram updates. |
| PostgreSQL | `database/engine.py` | Every call runs through `db_call` with a circuit breaker and timeout. |
| Cache | `database/cache/` | In-memory L1 always, optional Redis L2. |
| Scheduling | `database/scheduler/` | APScheduler with a SQLAlchemy job store; optional pg_cron ownership for database-only jobs. |
| MTProto | `database/mtproto.py` | Bot-token identity lookups with PostgreSQL-backed session storage. |

## Conventions

- Source files stay at or below 1,000 lines. Oversized modules split into a
  same-named package with a re-exporting `__init__.py`.
- Python 3.14 syntax, four-space indentation, and Ruff formatting.
- Configuration is parsed once in `tcbot/__init__.py`; no other module reads raw
  environment variables in the running application.
- All user-facing wording lives in `i18n/<locale>/*.toml`.
- There is no parse mode and no MarkdownV2 fallback send path.

Validation commands are listed in the [setup guide](../getting-started/setup.md).
