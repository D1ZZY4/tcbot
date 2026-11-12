# Supabase schema migrations

This directory records SQL migrations for the normalized Transsion Core schema.

The existing TCBot runtime still uses the legacy SQLAlchemy metadata in
`tcbot/database/base.py` and its Alembic history. The normalized schema in
`Transsion Core (Test)` is a different model and is not compatible with that
runtime yet. Do not point the current bot at the normalized database.

## Important migration-history limitation

The Supabase migration ledger currently contains the earlier normalized
schema migrations, but their original SQL source files have not all been
recovered into this repository. This directory currently records the
incremental migrations added during the current cutover preparation only.

A catalog-derived candidate baseline now exists at
[`bootstrap/normalized_schema.sql`](bootstrap/normalized_schema.sql). It
contains the current 28-table, three-view schema, constraints, indexes,
functions, triggers, comments, RLS settings, backend grants, and empty
federation/RBAC seed data. It deliberately contains no Telegram user IDs,
connected groups, moderation records, evidence content, MTProto credentials,
or scheduled jobs.

The baseline was executed in an isolated schema inside the existing
Development database and rolled back. Assertions covered object counts,
constraints, RLS, view security-invoker settings, backend-only relation and
sequence grants, function ACLs, and the initial RBAC catalog. A second
transaction also created a temporary table after installing a separately
named copy of the RLS event trigger and checked its RLS and privilege
behavior. Both transactions were rolled back. This is a useful SQL-level
restore check, but it is **not** a clean Supabase-project restore test:
Supabase-managed roles, extensions, default ACLs, platform event triggers,
PostgREST configuration, and project-level settings remain external
prerequisites.

The older migration sources are still missing, so the remote migration
ledger is not yet reproducible revision-for-revision from
`supabase/migrations/`. The runtime support tables also have a dedicated
ACL hardening migration that explicitly enables RLS, revokes client access,
and grants the required DML operations only to `service_role`; do not rely
on a pre-existing event trigger to supply those privileges. Treat the
snapshot as a candidate baseline for a separate empty staging project only
after reviewing its platform prerequisites and reconciling the migration
ledger. Do not run it against Production, a populated database, or the
active Development project.

Never mark a database migration as reproducible solely because its name
appears in the remote migration ledger.
