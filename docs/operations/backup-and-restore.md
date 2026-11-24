# Backup and restore

This page describes how to protect and restore the PostgreSQL state that TCF
Bot depends on. The bot has no built-in backup command, so operators own the
backup schedule and storage. The procedures below use standard PostgreSQL
tools.

Related pages: [database layer](../architecture/database.md),
[setup](../getting-started/setup.md), and
[runtime mechanics](../architecture/runtime.md).

## What must be backed up

The authoritative state is the schema selected by `DB_SCHEMA`:

| Schema | Back it up? | Reason |
|---|---|---|
| `public` | Yes, in deployment | The deployment's tables, data, and `alembic_version`. |
| `development` | Yes, if used | Operator work against a shared server. |
| `test` | No | Rebuilt and emptied by the test suite. |

Back up the whole schema, including reference data from `seed.sql` objects,
role assignments, moderation history, enforcement ledger tables, rules
publications, and `alembic_version`. The APScheduler job store
(`apscheduler_jobs`) is also in the schema; restoring it is optional, because
the bot reconciles schedules at startup.

Redis is a cache with no authoritative data. Do not back it up. After a Redis
loss the bot repopulates L1 and L2 from PostgreSQL.

## Before a backup

- Record the configured `DB_SCHEMA` and the deployed revision from
  `alembic_version`.
- Note the values of `MAIN_GROUP`, `MAIN_CHANNEL`, `PROOFS`, `LOGS`,
  `LOGS_ERRORS`, and `APPEALS`. These are runtime configuration, not database
  rows, and must exist in the target environment.
- Keep the credentials and the dump file out of the repository and out of
  public artifacts.

## Create a logical backup

For the deployment schema, a schema-scoped custom-format dump is the usual
choice:

```bash
pg_dump "$DATABASE_URL" \
  --schema=public \
  --format=custom \
  --file=tcbot-public.backup
```

For a non-public schema, replace `public` with the configured `DB_SCHEMA` value
(such as `development`). A plain SQL dump is also valid:

```bash
pg_dump "$DATABASE_URL" --schema=public --file=tcbot-public.sql
```

If the deployment uses pg_cron, capture its job definitions separately from
`cron.job`, because they live outside the application schema. Record the
`PG_CRON_ENABLED` setting as well.

## Restore

Restore into an empty or freshly reset target schema. Verify the target schema
name before running destructive steps.

```bash
pg_restore --dbname="$TARGET_DATABASE_URL" \
  --schema=public \
  --clean --if-exists \
  tcbot-public.backup
```

For a plain SQL dump, apply it with `psql` against the target database. After
the restore, query the `alembic_version` table and compare its value with the
newest revision in `alembic/versions/` (currently `0020_erased_identity_guard`). The bot applies any
pending revisions at startup, so a restored database behind the code head is
upgraded automatically.

## Post-restore checks

1. Start the bot against the restored database with the same `DB_SCHEMA`.
2. Confirm `/start` responds in private chat and the main menu renders.
3. Confirm `/tcgroups` lists the connected groups.
4. Confirm `/checkme` for the configured Owner shows the Owner role.
5. Confirm a read-only `/check` and `/tcstats` render without degraded notices.
6. Confirm the proof and log destinations receive a test action.
7. Verify that active bans and mutes are still reflected in the connected
   groups; replay can be forced by reconnecting a group if needed.

## Consistency notes

- The decision and its enforcement run commit in one transaction, so a logical
  backup taken outside a transaction may capture a decision without its run.
  Use `pg_dump` consistency and recheck unsettled runs with `/tcrepair` after a
  restore.
- Notification outbox rows are durable edits; a restored pending row is
  retried by the notification worker.
- A restore does not move Telegram state. Proof media and log posts remain in
  Telegram, and the database references to them remain valid as long as the
  target chat ids match.

## Security

- Encrypt backup files at rest and in transit.
- Do not include secrets, tokens, or private chat ids in log excerpts or
  documentation.
- Restrict access to dumps to the operators who need them.
- Test a restore periodically into the `development` schema rather than
  trusting an untested backup.

## Validation hints

Relevant tests include `tests/test_migrations.py`,
`tests/test_migration_bootstrap.py`, and `tests/test_schema_*.py`.
