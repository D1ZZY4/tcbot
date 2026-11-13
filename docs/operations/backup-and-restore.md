# Backup and Restore Runbook

Federation bans, staff roles, and connected groups are irreplaceable operational
data. Loss of any of these tables requires manual reconstruction from
moderator memory and audit logs. This document describes how to protect and
recover that data.

## Critical tables

| Table | Contents | Loss impact |
|---|---|---|
| `moderation_actions` | All active and historical ban, mute, warn, and kick decisions | Critical: bans cannot be reconstructed from Telegram |
| `moderation_cases` | The investigations the decisions belong to | Critical: the evidence trail of every decision |
| `role_assignments` | Staff role assignments | Critical: roles must be re-granted manually |
| `connected_chats` | Connected group registry | High: reconnecting requires each group admin to re-run `/tcconnect` |
| `moderation_appeals` | The appeal history of every ban | High: the decision trail of the review process |
| `telegram_users` | The Telegram identity registry | High: names and mentions stop resolving |
| `audit_events` | The immutable cross-domain event log | High: the audit trail of who decided what |
| `apscheduler_jobs` | Persistent scheduler data (APScheduler `SQLAlchemyJobStore`) | Medium: scheduler state may need verification after restore |

---

## Managed PostgreSQL or another hosted provider

Managed backup products (Neon, Supabase, RDS, Cloud SQL, and similar) or
scheduled `pg_dump` archives can protect the database. The exact backup
features, retention, and eligible tiers depend on the provider and plan.

### Enable backup

1. Open the cluster's backup or snapshots page in the provider console.
2. Enable the backup option available for the plan.
3. Choose retention that matches the recovery requirements of your deployment.
4. Verify that backup is **Active** in the cluster overview.

### Point-in-time restore

1. Select the desired restore point in the provider console.
2. Choose **Restore to this cluster** (overwrites existing) or
   **Restore to new cluster** (safer, then swap the connection string).
3. Monitor progress in the provider's restore job view.
4. After restore, verify counts:
   ```sql
   SELECT 'moderation_actions', count(*) FROM moderation_actions
   UNION ALL SELECT 'moderation_cases', count(*) FROM moderation_cases
   UNION ALL SELECT 'role_assignments', count(*) FROM role_assignments
   UNION ALL SELECT 'connected_chats', count(*) FROM connected_chats
   UNION ALL SELECT 'telegram_users', count(*) FROM telegram_users
   UNION ALL SELECT 'audit_events', count(*) FROM audit_events;
   ```

---

## Scheduled `pg_dump` archives

For deployments without a suitable managed backup, schedule a nightly
`pg_dump` or use the backup tooling provided by your database host.

### Prerequisites

```bash
# Debian / Ubuntu
sudo apt-get install -y postgresql-client
```

### Backup script

Create `/opt/tcbot/backup.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

DATABASE_URL="${DATABASE_URL:?DATABASE_URL is not set}"
BACKUP_DIR="/opt/tcbot/backups"
TIMESTAMP="$(date +%Y%m%dT%H%M%S)"
DEST="${BACKUP_DIR}/${TIMESTAMP}.dump"

mkdir -p "${BACKUP_DIR}"

# * --format=custom is a compressed archive that pg_restore can restore
# * selectively. --clean makes the restore drop the existing objects first.
pg_dump --dbname="${DATABASE_URL}" --format=custom --file="${DEST}"

# * Retain only the last 14 backups
find "${BACKUP_DIR}" -maxdepth 1 -name "*.dump" -printf '%T@ %p\n' \
  | sort -n | head -n -14 | awk '{print $2}' | xargs -r rm -f

echo "[$(date -Iseconds)] Backup complete: ${DEST}"
```

Make it executable:

```bash
chmod +x /opt/tcbot/backup.sh
```

### Schedule with cron

```bash
crontab -e
```

Add a line to run nightly at 02:00 UTC:

```cron
0 2 * * * /opt/tcbot/backup.sh >> /var/log/tcbot-backup.log 2>&1
```

### Offsite copy (optional but strongly recommended)

Pipe the archive to S3, Backblaze B2, or any rclone remote:

```bash
# After the pg_dump line in backup.sh, add:
rclone copy "${DEST}" remote:tcbot-backups/
```

---

## Restore from a `pg_dump` archive

```bash
# 1. Restore into an empty database (pg_restore creates the objects)
pg_restore --dbname="${DATABASE_URL}" --clean --if-exists --no-owner \
  /opt/tcbot/backups/20260101T020000.dump

# 2. To restore into a fresh database instead, create it first:
createdb --host=<host> --username=<user> tcbot_restored
pg_restore --dbname="postgresql://<user>:<password>@<host>:5432/tcbot_restored" \
  --no-owner /opt/tcbot/backups/20260101T020000.dump
```

Stop the bot before restoring. It applies the schema migrations at startup,
so a restore into a database that still holds the old tables is safe, but a
restore into a database with a newer schema version may conflict with the
migration the bot applies on the next boot.

---

## Post-restore checklist

After any restore, verify the bot starts cleanly and all subsystems are healthy:

```bash
uv run python -m tcbot &
curl http://localhost:${PORT:-5000}/health
```

Expected response shape (HTTP 200 when all core subsystems are ready):
```json
{
  "status": "ok",
  "database": "ok",
  "redis": "ok",
  "scheduler": "ok",
  "circuit_telegram": "closed",
  "circuit_database": "closed",
  "update_queue": 0,
  "ts": "2026-01-01T02:00:00+00:00"
}
```

`update_queue` is the PTB update-queue depth (`null` before the webhook
receiver is wired): a climbing value means the event loop is not keeping up
with Telegram, so watchdogs should page on it.

`redis` is `"disabled"` when `REDIS_URL` is not configured. A degraded response
uses HTTP `503`; inspect the individual fields before deciding whether a
restore or a restart is required. Note that `redis` is informational only:
the overall status (and the HTTP code) depends on the database, the scheduler,
and the circuit breakers, so `"redis": "error"` alone still returns 200.
The current ban command does not create
timed-ban schedules, so do not assume that every restore contains unban jobs.

---

## Schema migration note

The bot applies the pending Alembic revisions at startup, so a restored
database is brought to the current schema before the first handler query
reaches it. Run `uv run alembic current` against the restored database to
confirm the revision it is on, and `uv run alembic upgrade head` to apply
anything the restore left behind.

Protect the database account and backup archives with least-privilege access
and network restrictions.
