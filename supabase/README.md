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

Consequently, these files are **not yet a complete bootstrap history** for an
empty Supabase project. Before using Supabase CLI to recreate the normalized
schema from scratch or applying the normalized schema to Production, recover
and commit the missing historical migration sources (or produce and review a
complete baseline snapshot), then verify that the repository and remote
migration ledgers agree.

Never mark a database migration as reproducible solely because its name
appears in the remote migration ledger.
