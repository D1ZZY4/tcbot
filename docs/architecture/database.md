# Database layer

This page documents the PostgreSQL persistence layer in `tcbot/database/`:
schemas, the engine boundary, tables, schema objects, domain helpers, migrations,
and cache. The decision and worker lifecycle is in
[Persistence](../architecture/runtime.md) and the flow diagrams in
[the system spine](../flows/system.md).

## Schemas

The project uses exactly three PostgreSQL schemas and no fourth.

| Schema | Owner | Purpose |
|---|---|---|
| `public` | The deployment | Default schema; `DB_SCHEMA` defaults to it. |
| `test` | Integration tests | Built and emptied by `tests/postgres_support.py`; never holds deployment data. |
| `development` | A developer | Used by operator scripts and selected by `DB_SCHEMA=development`. |

`connection_options.schema_options()` pins `-c search_path=<DB_SCHEMA>` and
`-c timezone=UTC` on every engine, including the migration connection and the
APScheduler job store. Schema objects always land in the schema named by the
search path, not the one `current_schema()` would fall back to. A missing
schema is created at startup for non-public values.

## Engine and write boundary

`engine.py` owns the async SQLAlchemy engine and the session boundary.

- `connect()` applies Alembic migrations and creates the engine before any
  handler can query.
- `db_call(op, timeout=20.0)` runs one operation through the `postgres`
  circuit breaker and an `asyncio.timeout`. Every read and write goes through
  it, so a dead database fails fast for every caller.
- `run_transaction(op)` runs a callback on one session; all statements commit
  or roll back together. It already uses `db_call`, so callers must not nest another.
- `read_connection()` is an autocommit read path.
- The circuit opens after five transient failures within a window (successes in
  CLOSED do not reset the count) and admits one half-open probe after 60 seconds. Serialization failures, deadlocks, lock
  refusals, and statement cancellations prove the server is healthy and do not
  count toward the breaker. A saturated pool is a load condition, not a defect.

Feature modules must not build SQLAlchemy statements. All table access stays
in `*_db.py` helpers.

## Table groups

`tcbot/database/base/` declares the tables in domain modules and re-exports
them through `__init__.py`. `SCHEMA_TABLES` is the authoritative ordered list
that migrations apply.

| Group | Representative tables |
|---|---|
| Identity | `telegram_users`, `telegram_chats`, `connected_chats`, `chat_members`, `join_requests` |
| Roles and RBAC | `role_definitions`, `permission_definitions`, `role_permissions`, `role_assignments`, `promotion_requests` |
| Settings | `community_settings`, `user_settings`, `chat_settings` |
| Rules | `rule_sets`, `rule_set_versions`, `rule_categories`, `rule_items`, `rule_publications`, `rule_publication_runs`, `rule_acknowledgements` |
| Moderation | `moderation_cases`, `moderation_actions`, `moderation_evidence_uploads`, `moderation_evidence_items`, `moderation_messages`, `moderation_appeals`, `moderation_case_rules`, `moderation_notification_tasks`, `audit_events` |
| Enforcement | `moderation_enforcement_runs`, `moderation_enforcement_targets`, `moderation_enforcement_attempts` |
| Automation and broadcast | `automation_*`, `broadcast_campaigns`, `broadcast_targets`, `broadcast_attempts` |
| Jobs and runtime | `scheduled_jobs`, `scheduled_job_runs`, `retention_policies`, `telegram_user_erasures`, `apscheduler_jobs`, `mtproto_state` |

`documents.py` holds `TypedDict` row shapes and status `Literal` aliases.
`types.py` holds `NewType` domain primitives such as `UserId` and `BanId`.

## Schema objects and migrations

`tcbot/database/schema/` holds the SQL deployed from files. The loader applies,
in order, `views.sql`, `functions.sql`, `triggers.sql`, `policies.sql`, and
`seed.sql`. Each file carries a `%SCHEMA%` placeholder. The statement splitter
understands dollar-quoted function bodies, escape strings, and nested comments.
The seed defines role priorities (owner 100, admin 80, developer 60, moderator
40), permissions, and other reference data.

`alembic/versions/` holds numbered revisions; the current head is `0013`.
`database/migrations.py` applies them at startup under an advisory lock so two
instances cannot migrate concurrently. A schema bootstrapped from metadata but
missing `alembic_version` is stamped at the base revision before the normal
upgrade. See [Backup and restore](../operations/backup-and-restore.md).

## Domain helpers

| Path | Responsibility |
|---|---|
| `users_roles.py` | Role vocabulary, grants, rank checks, permissions, and ownership transfer. |
| `users_cache.py` | Member profiles, mention data, batch reads, and name search. |
| `bans_db/` | Ban decisions, appeals, review slots, and lifecycle writes. |
| `moderation_db.py` | Shared case, evidence, and decision write path. |
| `warns_db.py`, `kicks_db.py`, `mutes_db.py` | Domain-specific decision helpers. |
| `groups_db.py` | Connected groups, pending groups, and infrastructure destinations. |
| `queues_db.py` | Promotion requests and their expiry. |
| `enforcement_db.py` | Durable runs, targets, attempts, and connect replay. |
| `notifications_db.py` | Durable review-card edit outbox. |
| `rules_db/` | Drafts, categories, items, versions, publications, and runs. |
| `erasure_db.py` | Queued account erasures. |
| `settings_db.py` | Per-user and community default locale preferences; group locale lives in `groups_db.py`. |
| `pg_cron.py` | Optional pg_cron ownership of database-only jobs. |
| `scheduler/` | APScheduler wiring and scheduled maintenance jobs. |
| `mtproto.py`, `mtproto_store.py` | Bot-token MTProto client and its PostgreSQL session store. |

## Documents and status vocabulary

`BanDoc` is the composed ban view: the decision in `moderation_actions` joined
with its messages and appeal. Status values are `active`, `completed`, `revoked`,
`expired`, `superseded`, and `failed`. Request statuses are `pending`, `approved`,
`rejected`, `cancelled`, and `expired`.

Enforcement uses three tables: one row per run, one per target chat, and one per
delivery attempt. The target trigger accepts only `in_progress` to `succeeded`,
`skipped`, or `failed`; a retry is a failed row with a due deadline and never a
return to `pending`.

## Cache

`database/cache/` implements the two-level cache. L1 is an in-process TTL cache;
L2 is optional Redis under the `v2` namespace. A generation counter and a
cache-wide epoch discard results fetched across an invalidation, and a FIFO
mutation queue keeps writes, deletes, and clears ordered. Redis is never on the
critical path: a failed L2 read is a miss and a failed write is logged.

| Cache | Prefix | L1 TTL | L2 TTL |
|---|---|---|---|
| Effective role | `role` | 60 s | 90 s |
| Connected state | `conn` | 120 s | 180 s |
| Active groups | `groups` | 30 s | 45 s |
| Owner id | `owner` | 300 s | 360 s |
| User mention | `umention` | 300 s | 600 s |
| User locale | `ulocale` | 300 s | 600 s |
| Group locale | `glocale` | 300 s | 600 s |
| Community locale | `clocale` | 300 s | 600 s |

Role and owner reads fail closed. Enforcement reads pass `fresh=True` to bypass
caches. See [Runtime](runtime.md#cache-mechanics) for the invalidation guards.

## Validation hints

- `tests/test_engine_client.py`, `tests/test_db_call_transport.py`, and
  `tests/test_postgres_circuit.py` cover the engine boundary.
- `tests/test_schema_*.py` and `tests/test_migrations.py` cover schema objects.
- Database-backed tests use the `test` schema and skip when no server is configured.
