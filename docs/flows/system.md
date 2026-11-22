# System spine

This is the anchor flow page. It describes the runtime spine from startup through
update dispatch, authorization, persistence, and transport. The domain flows are
listed in the [flow index](README.md). The main domain pages are
[Banning](banning.md), [Unbanning](unbanning.md), [Kicking](kicking.md),
[Muting](muting.md), [Warning](warning.md), [Proof](proof.md),
[Appeals](appeals.md), [Connection](connection.md), [Roles](roles.md),
[Community rules](rules.md), and [Check and statistics](statistics.md).

## Topology

`flowchart` is used because the subject is the shape of the system and the
direction of data between components.

```mermaid
flowchart TD
    U[Telegram update] --> WEB["alive.py webhook or polling"]
    WEB --> PTB["python-telegram-bot Application"]
    PTB --> PROC["update_processor: per-conversation serialization"]
    PROC --> FILT["prefix and command filters"]
    FILT --> DEC["decorators: ratelimiter, tier guard, log_execution"]
    DEC --> CMD["Command handler in tcbot/modules"]
    CMD --> GATE["auth: guards, identity, extraction, targets"]
    GATE --> FLOW["Flow in helper/pipelines"]
    FLOW --> DB[("PostgreSQL via engine.db_call")]
    FLOW --> CACHE[("Redis L1 memory and optional L2 cache")]
    FLOW --> RICH["rich_msg / rich_edit with rich_message payload"]
    RICH --> U
    DB --> WK["enforcement_worker, notification_worker, scheduler"]
    WK --> U
```

## Startup sequence

`sequenceDiagram` is used because startup is an ordered set of calls between the
application, the database, the scheduler, and the Telegram transport.

```mermaid
sequenceDiagram
    participant Main as __main__.py
    participant Config as Configs
    participant DB as PostgreSQL
    participant Sched as APScheduler
    participant PTB as Telegram Application
    Main->>Config: load environment and validate required secrets
    Main->>DB: apply Alembic migrations in a worker thread
    Main->>DB: connect engine and prime caches
    Main->>Sched: register expiry retention and reconciliation jobs
    Main->>PTB: build application and discover modules
    PTB->>PTB: register command callback and message handlers
    Main->>PTB: set webhook or start polling fallback
```

Module discovery and the `MODULES_LOAD` and `MODULES_NO_LOAD` filters are
centralized in `tcbot/modules/__init__.py`. Webhook is the production path;
local development may fall back to polling. Shutdown drains Bot-dependent work
in `post_stop` while the client is still available, then closes external
clients in `post_shutdown`.

## Update dispatch layers

```mermaid
flowchart TD
    U[Update] --> KIND{Message or CallbackQuery}
    KIND -->|Message| M1[prefix resolution]
    M1 --> M2[command parser]
    M2 --> M3[rate limiter]
    M3 --> M4[tier guard owner staff mod basic mod permission]
    M4 --> M5[execution logging]
    M5 --> H[Handler]
    KIND -->|CallbackQuery| C1[q.answer before visible work]
    C1 --> C2[parse callback data segments]
    C2 --> C3[scope.callback_is_current]
    C3 -->|stale tap| DROP[acknowledge and discard]
    C3 -->|current| C4[re-authorize executor rank]
    C4 --> C5[rich edit of prompt]
    H --> F[Flow state machine]
```

Decorator order is fixed: `ratelimiter()` outermost, the required authorization
guard second, and `log_execution` innermost. Message-event handlers are exempt
from per-handler rate limits. Callback queries always call `q.answer()` first.

## Authorization and target resolution

Every moderation entry passes through the same chain. `guards.resolve_and_check()`
reads both roles fresh, refuses an executor below `min_role`, refuses an equal or
higher ranked target through `outranks()`, and fails closed on a lookup error.
`guards.classify_and_check()` runs `identity.classify()` alongside the rank check.

```mermaid
flowchart TD
    ENTRY[Command with optional target] --> ORIGIN{require_federation_origin}
    ORIGIN -->|denied| STOP[Reply and stop]
    ORIGIN -->|allowed| EX[extract_mod_target]
    EX --> VERIFY[verified ID or username or reply target]
    VERIFY --> CC[classify_and_check: identity plus fresh rank]
    CC --> VERDICT{Allowed}
    VERDICT -->|no| REFUSE[Refusal or retry notice]
    VERDICT -->|yes| PROTECTED{refuse_message hit}
    PROTECTED -->|yes| BLOCK[Block protected identity]
    PROTECTED -->|no| ACTION[Continue to flow]
```

There are two rank gates on a ban. The entry gate is `resolve_and_check()` with
`min_role="developer"` plus the `mod_only` decorator. The enforcement gate is
`guards.enforcement_refusal()` with the same tier, re-read fresh after the proof
window. A target promoted mid-window cannot be actioned by a moderator who no
longer outranks them. The full authorization contract is in
[Security](../architecture/security.md).

## Persistence and transport boundary

All database work goes through `engine.db_call()` or `engine.run_transaction()`,
which apply the circuit breaker and the call timeout. Decisions, cases, proof,
messages, and appeals live in the community moderation tables. Durable per-group
work lives in `moderation_enforcement_runs`, `moderation_enforcement_targets`,
and `moderation_enforcement_attempts`.

User-facing messages render through `rich_msg.py` and `rich_edit.py` using a
`rich_message` payload. Keyboards are rich buttons; cells that cannot be
expressed as rich buttons keep their inline keyboard. Plain notices and callback
alerts stay unparsed. No parse mode is used anywhere. Every decision commits to
PostgreSQL before any Telegram call, and unfinished per-group deliveries are
queued for the workers described in [Runtime](../architecture/runtime.md).
