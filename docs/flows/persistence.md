# Persistence, workers, and schedules

This document describes how a moderation decision becomes durable state, how its
Telegram delivery is queued and retried, and which jobs own expiry and retention.
The write boundary is owned by `database/engine.py` and described in
[the database layer](../architecture/database.md).

## Storage topology and schemas

The process writes to exactly one PostgreSQL schema, selected by `DB_SCHEMA`
through the libpq `search_path`. The project uses three schemas and no fourth.

| Schema | Owner | Purpose |
|---|---|---|
| `public` | The deployment | Default schema; `DB_SCHEMA` defaults to it. |
| `test` | Integration tests | Built and emptied by `tests/postgres_support.py`; never holds deployment data. |
| `development` | A developer | Used by operator scripts and selected by `DB_SCHEMA=development`. |

`connection_options.schema_options()` pins `-c search_path=<DB_SCHEMA> -c timezone=UTC`
on every engine, including the migration connection and the APScheduler job
store. Schema objects always land in the schema the connection was pointed at,
read from the search path rather than `current_schema()`.

```mermaid
flowchart TD
    H[Handlers and database helpers] --> BC[engine.db_call: circuit breaker plus 20s timeout]
    BC -->|OPEN| REJ[Reject with CircuitOpenError]
    BC -->|CLOSED or HALF_OPEN| TX[run_transaction: one session and one transaction]
    TX --> C[Commit or rollback as one unit]
    TX --> SP[search_path from DB_SCHEMA]
    SP --> PUB[(public: deployment)]
    SP --> DEV[(development: operator)]
    SP --> TST[(test: integration tests)]
```

## Write boundary

Every read and write goes through `engine.db_call(op, timeout=20.0)`, so the
event loop never blocks on database I/O and a dead database fails fast for
every caller.

| Boundary | Behavior |
|---|---|
| `db_call` | Runs one operation through the `postgres` circuit breaker and a 20 s `asyncio.timeout`. |
| `run_transaction` | Runs a callback on one session; all statements commit or roll back together. It already uses `db_call`, so callers must not nest another. |
| `session` | Commits on success, rolls back on failure; rollback is best effort and never replaces the original exception. |
| `read_connection` | Autocommit read path using the shared `_read_engine` proxy so checkouts skip per-call `execution_options()`; a SELECT avoids the cost of closing a transaction. |
| Circuit `postgres` | Opens after 5 consecutive transient failures; one HALF_OPEN probe after 60 s; a success closes it. |
| Counted failures | Dropped connections, refused sockets, driver timeouts, pool timeouts, caller-side timeouts. |
| Ignored failures | SQLSTATE `40001`, `40P01`, `55P03`, `57014` (serialization failure, deadlock, lock refusal, statement cancellation) prove the link is healthy. |

### Decision and enforcement run in one transaction

A decision is never committed without the run that delivers it. The flow opens
a case under an advisory lock, archives proof, links selected rules, queues the
enforcement run with a stable idempotency key, and closes the case, all on the
session given by `run_transaction`. The Telegram call happens only after the
commit.

```mermaid
sequenceDiagram
    participant F as Moderation flow
    participant H as Database helpers
    participant PG as PostgreSQL
    participant W as Enforcement worker
    participant TG as Telegram
    F->>H: open_case with pg_advisory_xact_lock on case
    H->>PG: ensure_users, case, evidence, run, close case
    PG-->>H: action id and run id
    H-->>F: decision committed with queued run
    Note over F,W: Commit precedes every Telegram call
    W->>PG: requeue_stale_runs then claim_runs with FOR UPDATE SKIP LOCKED
    PG-->>W: claimed run
    W->>PG: load_run_action and claim_targets
    PG-->>W: action and up to 100 targets
    W->>TG: fan_out apply, revoke, or reconcile
    TG-->>W: per-target result
    W->>PG: complete_target with attempt row and optional retry deadline
```

A manual unban, an approved appeal, and a kick repair follow the same rule: the
decision status, appeal settlement, review-slot release, and the `revoke` or
`reconcile` run are written in one transaction.

## Enforcement worker lifecycle

The database records decisions and per-group delivery work in three tables:
`moderation_enforcement_runs` (one action, one `apply`, `revoke`, or `reconcile`
operation, an idempotency key, a status), `moderation_enforcement_targets` (one
chat per run), and `moderation_enforcement_attempts` (one row per delivery
attempt). `MAX_ATTEMPTS` is 3, shared by the worker and the stale-run requeue.

```mermaid
flowchart TD
    T[Scheduled tick] --> R[requeue_stale_runs after 30 minutes]
    R --> C{Telegram circuit}
    C -->|OPEN| SKIP[Skip tick and keep runs queued]
    C -->|HALF_OPEN| PROBE[Claim one run and one target probe]
    C -->|CLOSED| CLAIM[Claim runs bounded by admission headroom]
    PROBE --> CHECK[load_run_action validates operation and conflicts]
    CLAIM --> CHECK
    CHECK -->|unsupported, superseded, expired, or no action| CANCEL[cancel_run with stored reason]
    CHECK -->|valid| DELIVER[chunked fan_out bounded delivery with timeout]
    DELIVER --> OK[complete_target succeeded]
    DELIVER --> BENIGN[complete_target skipped]
    DELIVER --> PERM[complete_target failed permanent terminal]
    DELIVER --> TRANS{attempts under 3}
    TRANS -->|yes| RETRY[complete_target failed with 5 minute retry]
    TRANS -->|no| TERM[complete_target failed terminal]
```

An OPEN circuit skips the claim entirely, because a slot skipped by the breaker
never reaches Telegram and must not consume one of the three attempts. HALF_OPEN
admits a single probe so a recovering circuit cannot burn the federation retry
budget. `run_once` claims at most 10 runs per tick; each run delivers in chunks
sized by the breaker's `admission_headroom`, so a circuit that opens mid-batch
cannot leave later claimed targets skipped without a call.

```mermaid
stateDiagram-v2
    [*] --> queued
    queued --> running : claim_runs or claim_run
    running --> completed : all targets succeeded or skipped
    running --> partial : failed targets with no due retry
    running --> failed : failed targets terminal
    running --> cancelled : superseded, expired, missing action, or kick covered by a ban
    running --> queued : stale requeue or a target retry is due
    partial --> queued : requeue_stale_runs sees a due retry
    failed --> queued : operator redrive_run
    completed --> [*]
    cancelled --> [*]
```

| Run status | Meaning |
|---|---|
| `queued` | Waiting to be claimed by a worker tick. |
| `running` | Owned by a worker; targets are being delivered. |
| `completed` | Every target succeeded or was skipped. |
| `partial` | At least one target failed and no retry is due. |
| `failed` | Delivery failed with no in-flight target. |
| `cancelled` | Terminal and explained under `metadata.cancel_reason`. |

```mermaid
stateDiagram-v2
    [*] --> pending
    pending --> in_progress : claim_targets
    in_progress --> succeeded : Telegram accepted
    in_progress --> skipped : benign refusal, nothing to do
    in_progress --> failed : transient or permanent failure
    failed --> in_progress : retry due and claimed again
    failed --> failed : redrive sets next_retry_at to now
    succeeded --> [*]
    skipped --> [*]
```

| Target status | Meaning |
|---|---|
| `pending` | Not yet claimed. |
| `in_progress` | Delivery in flight; a stale one is released after 30 minutes. |
| `succeeded` | Telegram accepted the ban, restriction, or unban. |
| `skipped` | Benign refusal, such as a user who is not in the group. |
| `failed` | Delivery refused; carries `error_kind`, `last_error_detail`, and an optional `next_retry_at`. |

The target trigger only accepts `in_progress` to `succeeded`, `skipped`, or
`failed`. A retry is a `failed` row with a due deadline, never a return to
`pending`. A target stranded past the stale window becomes `failed` with a due
retry, or terminal with `attempts_exhausted` when its budget is spent, so a
Telegram outage cannot grant a fourth delivery.

`load_run_action` evaluates conflict guards in the same query: a `revoke` is
cancelled when a newer active decision of the same type is in force, a kick
`reconcile` is cancelled when an active federation ban holds the target, and an
`apply` whose deadline passed while queued is cancelled rather than served late.

### Repair redrive

`redrive_run()` is the operator path back into a failed run. It locks the run,
refuses one already `queued` or `running`, refuses a `cancelled` run, and moves
every failed target (or only the requested chat) to a due retry deadline before
returning the run to `queued`. The original decision and run are kept, so a
repair never files a second verdict. `/tcrepair` exposes the unsettled runs and
this retry. See also [Unbanning](unbanning.md).

## Notification worker outbox

`moderation_notification_tasks` is the durable outbox for review-card edits
whose direct Telegram update failed. The manual-unban revocation queues its card
edit in the same transaction as the decision, so a settled appeal cannot leave
a live-looking card.

```mermaid
stateDiagram-v2
    [*] --> pending
    pending --> pending : claim increments attempts and sets next retry
    pending --> sent : edit landed or message not modified
    pending --> skipped : card still live, message gone, or forbidden
    pending --> failed : five attempts exhausted or worker error
    sent --> [*]
    skipped --> [*]
    failed --> [*]
```

| Task state | Meaning |
|---|---|
| `pending` | Due for an edit; claim advances `attempts` and sets `next_retry_at`. |
| `sent` | The card was closed in Telegram, or Telegram reported "not modified". |
| `skipped` | Still the live review of an active decision with a pending appeal, or the message is gone or forbidden. |
| `failed` | Terminal after 5 attempts at 5 minute intervals, an invalid identifier, or a worker error at the ceiling. |

The worker pauses on an OPEN Telegram circuit and admits one probe in HALF_OPEN.
`complete_task(..., expected_attempts=..., expected_message_id=...)` applies the
update only while the exact claim is still the current pending row, so a
re-queued task with a newer card cannot be overwritten by a previous worker
result. A card that is still the live review with a pending appeal is skipped
instead of closed. See [Appeals](appeals.md).

## Scheduler and pg_cron ownership

APScheduler 3.11.3 runs an `AsyncIOScheduler` with a `SQLAlchemyJobStore` table
`apscheduler_jobs` in the configured schema. Schedules are reconciled on startup
by comparing stored jobs once in memory, and UTC is explicit. The runtime passes
the enforcement and notification worker callables into the scheduler, so the
storage layer never imports Telegram delivery modules.

| APScheduler job ID | Cadence | Purpose |
|---|---|---|
| `tcbot.expiry_daily` | 24 h | Expire decisions and queue revokes; removed when pg_cron owns this. |
| `tcbot.promotion_expiry_hourly` | 1 h | Mark stale promotion requests `expired`. |
| `tcbot.enforcement_worker` | 5 min | Drain the enforcement run queue once. The ID is stable for persisted schedules; the callable now lives in `moderation_enforcement.py`. |
| `tcbot.notification_worker` | 5 min | Retry due review-card edits once. |
| `tcbot.erasure_every_10m` | 10 min | Drain up to 25 queued account erasures. |
| `tcbot.retention_daily` | 24 h | Apply schema retention policies. |
| `tcbot.stale_cleanup_daily` | 24 h | Delete stale memberships and drain erasures. |

Retired schedule IDs removed on every startup are `tcbot.warn_expiry_daily`,
`tcbot.db_cleanup_weekly`, and `tcbot.enforcement_sync`. Their functions stay
importable so a persisted job record can still be deserialized.

pg_cron is opt-in through `PG_CRON_ENABLED` and only used when the extension
exists. Its job names match the `scheduled_jobs` registry keys.

| pg_cron job | Schedule | Purpose |
|---|---|---|
| `moderation.expire` | `*/5 * * * *` | Expire decisions and queue revokes. |
| `role.expire` | `*/10 * * * *` | Expire role assignments with audit events. |
| `enforcement.reconcile` | `*/5 * * * *` | Release stranded enforcement targets. |
| `scheduler.drift` | `*/15 * * * *` | Audit the registry against `cron.job`. |

```mermaid
flowchart TD
    S[sync_schedules] --> E{PG_CRON_ENABLED and extension present}
    E -->|no| APS[Keep APScheduler schedules and remove stale pg_cron jobs]
    E -->|yes| REG[Register all four pg_cron jobs]
    REG --> OK{Every job registered}
    OK -->|yes| ONLY[Remove the APScheduler expiry schedule; pg_cron is sole owner]
    OK -->|no| SWEEP[Remove every owned pg_cron job and fall back to APScheduler]
```

A partial hand-off removes all pg_cron jobs this module owns, including entries
from an earlier boot, so the two owners can never run the same sweep at once.

## Expiry, retention, and erasure

```mermaid
flowchart TD
    E[expire_due_decisions] --> L[advisory lock tcbot:expiry]
    L --> F1[expire_due_moderation_actions_and_queue_revokes]
    L --> F2[expire_due_role_assignments_and_audit]
    F1 --> R[Revoke runs queued in the same transaction]
    C[expire_stale_records] --> C1[Delete chat_members older than 90 days]
    C --> C2[Drain up to 25 erasure requests]
    C2 --> I[Invalidate mention, role, and locale caches after commit]
    RET[sweep_retention] --> J[run_scheduled_job with a day-scoped run key]
    J --> REC[Record the run in scheduled_job_runs]
```

The APScheduler expiry transaction holds a cross-instance advisory lock, so two
schedulers cannot expire the same rows or queue duplicate revokes. When pg_cron
owns the expiry work, the scheduled-job registry claim is the duplicate guard
instead: the hand-off removes the APScheduler job, and the SQL sweep is
idempotent. A failed removal leaves both owners firing, but the claim and the
idempotent status updates still prevent a duplicate revoke. Warning expiry needs
no row rewrite because warn counters read the deadline at query time. A timeout
fails the run loudly instead of reporting a completed expiry. Erasure and
membership cleanup are separate transactions; their cache invalidation runs
before the failure verdict so an erased name cannot be served from either cache
layer for the whole TTL. The retention sweep uses a day-scoped run key, so two
instances firing minutes apart still produce one sweep for the day.
