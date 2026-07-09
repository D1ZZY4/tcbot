# Project Mapping

For project overview, see [`../README.md`](../README.md). For runtime state and priorities, see [`../PLAN.md`](../PLAN.md). For module breakdown, see [`modules/modules.md`](modules/modules.md). For database layer, see [`databases/databases.md`](databases/databases.md). For shared helpers, see [`helper/helper.md`](helper/helper.md). For runtime utilities, see [`utils/utils.md`](utils/utils.md).

This page maps the repository structure and the service boundaries between packages.

## Top-level layout

```text
<project root>/
├── tcbot/                  Main Python package
├── docs/                   Developer documentation
├── .agents/                Agent config (rules/, skills/, agents/)
├── pyproject.toml          Dependencies and Ruff config
├── uv.lock                 Locked dependency graph
├── config.env.example      Environment variable template
├── AGENTS.md               Contributor and agent guidelines
├── PLAN.md                 Project plan and backlog
├── README.md               Project overview
├── replit.md               Replit deployment notes
├── CHANGELOG.md            Version history
├── docker-compose.yml      Bot + MongoDB local stack
└── Dockerfile              Container image
```

## Runtime package map

```text
tcbot/
├── __init__.py             Environment loader and cfg adapter
├── __main__.py             PTB app setup, DB init, handler registration, polling
├── alive.py                Flask health endpoint and webhook receiver
├── database/
│   ├── mongos.py           Motor client, collection accessor, indexes
│   ├── bans_db.py          Federation ban records (incl. per-user history)
│   ├── groups_db.py        Connected groups and pending joins
│   ├── users_cache.py      Member profile cache operations
│   ├── users_roles.py      Owners/admins + dev/tester roles, effective-role resolution
│   ├── warns_db.py         Warnings and warning counters (incl. per-user aggregates)
│   ├── kicks_db.py         Kick audit records (incl. per-user history)
│   ├── mutes_db.py         Mute audit records (incl. per-user history)
│   ├── queues_db.py        Promotion request queue
│   ├── cache.py            Single-process TTL caches
│   ├── documents.py        TypedDict document shapes
│   └── types.py            NewType ID primitives
├── modules/
│   ├── __init__.py         Dynamic module discovery and handler collection
│   ├── types.py            Shared handler type aliases (CommandHandlerFn, etc.)
│   ├── *.py                Command and callback modules
│   └── helper/
│       ├── decorators.py   Auth, per-handler rate limits, tracing, resolve_and_check
│       ├── extraction.py   Target resolution
│       ├── formatter.py    HTML escaping and formatting
│       ├── keyboards.py    Inline keyboard factories
│       ├── ban_info.py     Ban detail renderer
│       ├── identity.py     Identity classification, refusal messages, staff notices
│       ├── replies.py      Shared reply string constants (errors, permissions, syntax)
│       ├── parse_*.py      Link, log, and safe-edit helpers
│       └── workflows/
│           └── *_flow.py   Conversation factories, plus Promote / Demote / Check classes
└── utils/
    ├── circuit_breaker.py  Async circuit breaker for Telegram + MongoDB
    ├── dispatch.py         Bounded concurrent fan-out (integrates Telegram circuit)
    ├── error_reporter.py   Telegram error classification and reporting
    ├── logger.py           Console formatter and error log handler
    ├── pagination.py       Shared paginate(), nav_row(), date_or_unknown() helpers
    ├── prefixes.py         Prefix parsing and command filters
    └── timedate_format.py  UTC datetime helpers
```

## Ownership boundaries

| Area | Owns | Must not own |
|---|---|---|
| `tcbot/__main__.py` | Application startup, global handlers, DB init, polling | Feature business logic |
| `tcbot/modules/*.py` | Command entry points, handler registration, user-facing permissions | Raw MongoDB writes, duplicate conversation state handlers |
| `tcbot/modules/helper/` | Shared handler helpers and keyboard factories | Top-level command registration |
| `tcbot/modules/helper/workflows/*_flow.py` | Conversation factories, state transitions, flow executors | Module discovery or `__handlers__` exports |
| `tcbot/database/*_db.py` | Collection-specific DB operations | Telegram API calls |
| `tcbot/utils/` | Runtime infrastructure utilities | Feature-specific moderation policy |

```mermaid
graph TD
    Main[__main__.py] -->|registers handlers from| Mods[modules/*.py]
    Main -->|initialises| DB[database/]
    Main -->|starts| Alive[alive.py]
    Mods -->|calls helpers from| Helper[modules/helper/]
    Mods -->|calls flows from| Flows[helper/workflows/*_flow.py]
    Helper -->|reads/writes via| DB
    Flows -->|reads/writes via| DB
    Flows -->|fan-out via| Utils[utils/dispatch.py]
    Utils -->|guarded by| CB[utils/circuit_breaker.py]
    CB -->|Telegram API| TG[Telegram]
    Mods -->|Telegram API| TG
    Alive[alive.py] -->|reads state from| CB
```

## Startup flow

```mermaid
sequenceDiagram
    participant Proc as uv run python -m tcbot
    participant Config as tcbot.__init__
    participant Main as tcbot.__main__
    participant Alive as tcbot.alive
    participant DB as database.mongos
    participant Mods as tcbot.modules
    participant PTB as PTB Application

    Proc->>Config: load env into cfg
    Proc->>Main: call main()
    Main->>Main: setup logging
    Main->>Alive: start Flask health thread
    Main->>PTB: build Application (post_init registered as callback)
    Main->>Mods: get_handlers()
    Mods->>Mods: discover, filter, import modules
    Mods-->>Main: handlers
    Main->>PTB: add handlers and error handler
    Main->>PTB: run_polling()
    PTB->>Main: run post_init (before polling starts)
    Main->>DB: connect() and ensure_indexes()
    Main->>DB: ensure_initial_owner()
    Main->>Main: connect Redis (optional)
    Main->>Main: start APScheduler
    Main->>Main: attach error_reporter + asyncio handler
    PTB->>PTB: start polling loop
```

## Dynamic module discovery

`tcbot/modules/__init__.py` discovers every top-level `tcbot/modules/*.py` file except `__init__.py`.

Filtering order:

1. If `MODULES_LOAD` is set, only those module names are loaded. Invalid names cause startup to exit.
2. If `MODULES_NO_LOAD` is set, matching names are removed from the discovered list.
3. `get_handlers()` imports active modules and extends the application handler list with each module's `__handlers__`.

Module names are filenames without `.py`, for example `banning`, `appeals`, or `maintenance`.

## Request handling layers

```mermaid
flowchart TD
    Update[Telegram update] --> GlobalRate[global_rate_limit_handler group -1]
    GlobalRate --> ModuleHandler[Module handler]
    ModuleHandler --> Decorators[ratelimiter + role decorator + log_execution]
    Decorators --> Entry[cmd_* or on_* function]
    Entry --> Helper[helper functions]
    Helper --> DB[database helper]
    Entry --> Flow[workflow executor if needed]
    Flow --> FanOut[utils.dispatch.fan_out]
    FanOut --> Telegram[Telegram API]
```

## Cross-links

- Setup and environment: [setup.md](setup.md)
- Command modules: [modules/modules.md](modules/modules.md)
- Workflows: [workflows.md](workflows.md) and [workflows/workflows.md](workflows/workflows.md)
- Database layer: [databases/databases.md](databases/databases.md)
- Shared helpers: [helper/helper.md](helper/helper.md)
- Runtime utils: [utils/utils.md](utils/utils.md)
