# Security Policy

## Reporting a vulnerability

Do not open a public issue for anything that could put groups, users, or
credentials at risk (authentication or authorization bypass, privilege
escalation, secret exposure, remote execution). Instead, contact a
maintainer privately with:

- the affected version or commit,
- what an attacker could do with it,
- steps to reproduce that use only placeholder credentials and IDs.

Never include real bot tokens, database URLs, webhook secrets, private chat
IDs, or raw private user data in any report or public discussion.

## Scope notes

- `apscheduler==3.11.3` is pinned with an accepted CVE-2026-31072 exception
  (see `CHANGELOG.md`). The scheduler stores its jobs in the `apscheduler_jobs`
  table through `SQLAlchemyJobStore`, which serializes the job state with
  `pickle`. The table lives in the bot's own database, so the exposure is
  bounded by that database's write access: treat the database role as
  trusted, restrict it to the bot, and never point `DATABASE_URL` at a
  database that another principal can write to. Reports against this pin
  should propose a compatible migration path, not just a version bump.
- Automated findings (CodeQL, Dependabot, secret scanning) are triaged
  against actual exploitability in this codebase before any change ships.
