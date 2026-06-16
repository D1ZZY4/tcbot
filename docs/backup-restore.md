# TCF Bot: Backup and Restore Runbook

Federation bans, staff roles, and connected groups are irreplaceable operational
data. Loss of any of these collections requires manual reconstruction from
moderator memory and audit logs. This document describes how to protect and
recover that data.

## Critical collections

| Collection | Contents | Loss impact |
|---|---|---|
| `tc_bans` | All active and historical federation bans | Critical: bans cannot be reconstructed from Telegram |
| `tc_owners` / `tc_admins` / `tc_roles` | Staff role assignments | Critical: roles must be re-granted manually |
| `tc_groups` | Connected group registry | High: reconnecting requires each group admin to re-run `/tcconnect` |
| `warn_counts` / `tc_warns` | Warning records | Medium: warn history lost; users get a clean slate |
| `apscheduler_jobs` | Persistent scheduled jobs (e.g. timed unbans) | Medium: jobs must be re-created manually on restore |

---

## MongoDB Atlas (recommended)

Atlas Continuous Backup or Shared/Dedicated Snapshot Backup is the easiest
and most reliable option.

### Enable backup

1. In the Atlas console, open your cluster → **Backup**.
2. Enable **Continuous Cloud Backup** (M10+) or **On-Demand Snapshots** (any
   tier).
3. Set retention: at minimum **7 days** for continuous backup, **3 snapshots**
   for on-demand.
4. Verify that backup is **Active** in the cluster overview.

### Point-in-time restore

1. In the Atlas console, open the cluster → **Backup → Snapshots** (or the
   continuous-restore timeline).
2. Select the desired restore point.
3. Choose **Restore to this cluster** (overwrites existing) or
   **Restore to new cluster** (safer, then swap connection string).
4. Monitor progress in the **Restore Jobs** tab.
5. After restore, verify counts:
   ```
   db.tc_bans.countDocuments()
   db.tc_groups.countDocuments()
   db.tc_roles.countDocuments()
   ```

---

## Self-hosted or Atlas free tier: `mongodump` cron

For deployments without Atlas paid backup, schedule a nightly `mongodump`.

### Prerequisites

```bash
# Debian / Ubuntu
sudo apt-get install -y mongodb-tools

# or via the MongoDB tools tarball from https://www.mongodb.com/try/download/tools
```

### Backup script

Create `/opt/tcbot/backup.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

MONGODB_URI="${MONGODB_URI:?MONGODB_URI is not set}"
DB_NAME="${DB_NAME:-tcbot}"
BACKUP_DIR="/opt/tcbot/backups"
TIMESTAMP="$(date +%Y%m%dT%H%M%S)"
DEST="${BACKUP_DIR}/${TIMESTAMP}"

mkdir -p "${DEST}"
mongodump --uri="${MONGODB_URI}" --db="${DB_NAME}" --out="${DEST}"
tar -czf "${DEST}.tar.gz" -C "${BACKUP_DIR}" "${TIMESTAMP}"
rm -rf "${DEST}"

# Retain only the last 14 backups
find "${BACKUP_DIR}" -maxdepth 1 -name "*.tar.gz" -printf '%T@ %p\n' \
  | sort -n | head -n -14 | awk '{print $2}' | xargs -r rm -f

echo "[$(date -Iseconds)] Backup complete: ${DEST}.tar.gz"
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
# After the tar line in backup.sh, add:
rclone copy "${DEST}.tar.gz" remote:tcbot-backups/
```

---

## Restore from `mongodump` archive

```bash
# 1. Extract the archive
tar -xzf /opt/tcbot/backups/20260101T020000.tar.gz -C /tmp/

# 2. Restore (additive; does not drop existing data)
mongorestore --uri="${MONGODB_URI}" --db="${DB_NAME}" \
  /tmp/20260101T020000/${DB_NAME}/

# 3. To replace existing data entirely, add --drop
mongorestore --uri="${MONGODB_URI}" --db="${DB_NAME}" --drop \
  /tmp/20260101T020000/${DB_NAME}/
```

---

## Post-restore checklist

After any restore, verify the bot starts cleanly and all subsystems are healthy:

```bash
uv run python -m tcbot &
curl http://localhost:${PORT:-5000}/health
```

Expected response shape (HTTP 200):
```json
{
  "mongodb": "ok",
  "redis": "ok",
  "scheduler": "ok",
  "status": "ok",
  "ts": "2026-01-01T02:00:00.000000"
}
```

If `scheduler` is `degraded`, APScheduler's `apscheduler_jobs` collection may
be partially restored. Re-create any time-critical jobs (e.g. timed unbans) via
the bot commands that originally created them.

---

## Scheduler CVE note

APScheduler 4.0.0a6 (CVE-2026-31072, CVSS 9.8) deserializes job payloads from
MongoDB. A tampered `apscheduler_jobs` document could trigger arbitrary code
execution on the bot host. Access controls that reduce backup-restore risk also
reduce CVE reachability:

- Restrict `MONGODB_URI` to a dedicated database user with
  **read/write on `tcbot` only** (no `admin` or `local` access).
- Enable MongoDB Atlas IP Access List or network peering.
- Rotate `MONGODB_URI` immediately if a breach is suspected.

See PLAN.md → Core Subsystem Design / Persistent Scheduler for full CVE
analysis and the accepted-risk rationale.
