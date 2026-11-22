# TCF Bot Documentation

This directory is the maintained documentation set for TCF Bot, the Python
Telegram bot for the Transsion Core Federation. It is written for operators,
members, and contributors. Every page describes current behavior in this
checkout.

Use this page as the index. For the user-facing overview, see
[`../README.md`](../README.md). For hosted deployment notes, see
[`../replit.md`](../replit.md). For the contribution workflow, see
[`../CONTRIBUTING.md`](../CONTRIBUTING.md). Release history lives in
[`../CHANGELOG.md`](../CHANGELOG.md) and in [`releases/`](releases/v7.1.0.md).

## Documentation map

### Getting started

| Document | Purpose |
|---|---|
| [Setup guide](getting-started/setup.md) | Local, Docker, and hosted setup, required environment variables, and validation commands. |

### Architecture

| Document | Purpose |
|---|---|
| [Repository map](architecture/repository-map.md) | Directory layout, package ownership, startup sequence, and service boundaries. |
| [Modules](architecture/modules.md) | Command modules, discovery, handler registration, and command ownership. |
| [Database layer](architecture/database.md) | PostgreSQL schemas, tables, helpers, transactions, and cache rules. |
| [Helper package](architecture/helpers.md) | Decorators, guards, extraction, pipelines, buttons, messages, and rich transport. |
| [Runtime utilities](architecture/utilities.md) | Circuit breaker, bounded dispatch, prefixes, logging, error reporting, and time helpers. |

### Pipelines

Every diagram in this documentation set lives under `pipelines/`. The prose
pages below describe behavior but do not draw diagrams; they point here
instead. [`banning.md`](pipelines/banning.md) is the anchor page: it draws the
full system spine and the end-to-end ban flow, and the other pages zoom into
one domain each.

| Document | Purpose |
|---|---|
| [Banning and system spine](pipelines/banning.md) | Full system spine, ban flow, and enforcement lifecycle. |
| [Unbanning](pipelines/unbanning.md) | Fail-closed revoke, atomic queue, and durable delivery. |
| [Kicking](pipelines/kicking.md) | Current-chat ban, rejoin, and reconcile repair. |
| [Muting](pipelines/muting.md) | Duration, apply and revoke runs, and connect replay. |
| [Warning](pipelines/warning.md) | Per-group and federation thresholds, exemption, and clearing. |
| [Proof](pipelines/proof.md) | Media filter, debounce, flush claim, and proof archive. |
| [Appeals](pipelines/appeals.md) | Submission, review windows, and staff decisions. |
| [Connection](pipelines/connection.md) | Connect, replay, join enforcement, and disconnect. |
| [Roles](pipelines/roles.md) | Promotion, demotion, and ownership transfer. |
| [Permissions](pipelines/permissions.md) | Tier gates, permission catalog, and guards. |
| [Extraction and user data](pipelines/extraction-user-data.md) | Target resolution, identity, and the member cache. |
| [Rate limiting](pipelines/ratelimit.md) | Throttles, global limiter, and circuit breaker. |
| [Persistence](pipelines/persistance.md) | Transactions, workers, scheduler, and pg_cron. |
| [Cache](pipelines/cache.md) | L1 and L2 caches, invalidation, and stale-read guards. |
| [Rules](pipelines/rules.md) | Editor, publication, acknowledgment, and the shared picker. |
| [Transport](pipelines/transport.md) | Rich send and edit, rich buttons, and audit logs. |
| [Callbacks](pipelines/callbacks.md) | Exhaustive state and callback payload registry. |
| [Check and statistics views](pipelines/statistics.md) | Check and stats drill-down trees, pagination, and batched reads. |

### Features

| Document | Purpose |
|---|---|
| [Flow overview](features/flow-overview.md) | User-visible moderation, appeal, connection, role, and statistics flows. |
| [Banning](features/moderation/banning.md) | Federation ban, proof, updates, logs, and appeal links. |
| [Kicking](features/moderation/kicking.md) | Current-chat kick, reason and proof steps, and audit log. |
| [Muting](features/moderation/muting.md) | Timed mute, unmute, replay, and edge cases. |
| [Warning](features/moderation/warnings.md) | Per-group warnings, thresholds, and automatic bans. |
| [Unbanning](features/moderation/unbanning.md) | Manual unban, fail-closed gates, and revoke delivery. |
| [Appeals](features/moderation/appeals.md) | Appeal deep links, submission, and review decisions. |
| [Check](features/moderation/check.md) | Self status and the comprehensive user profile view. |
| [Connecting](features/moderation/connecting.md) | Group connect, replay, and join enforcement. |
| [Disconnecting](features/moderation/disconnecting.md) | Group disconnect and force remove. |
| [Groups](features/moderation/groups.md) | Connected-groups listing and view toggles. |
| [Community rules](features/moderation/rules.md) | Rules editor, publication, acknowledgment, and picker. |
| [Roles](features/roles/roles.md) | Owner, Admin, Developer, and Moderator hierarchy and safety rules. |
| [Promote](features/roles/promote.md) | Direct promotion and the queued Admin request. |
| [Demote](features/roles/demote.md) | Manual and automatic demotion. |
| [Language](features/language.md) | Locale preferences, the TOML catalog, and the selection flow. |
| [Statistics](features/statistics.md) | Federation stats, drill-downs, and ban search. |
| [Miscellaneous modules](features/misc-modules.md) | Start, help, about, privacy, greeting, broadcast, maintenance, and network tools. |

### Operations

| Document | Purpose |
|---|---|
| [Backup and restore](operations/backup-and-restore.md) | PostgreSQL backup and restore procedures and post-restore checks. |
| [CI/CD workflows](operations/ci-cd.md) | GitHub Actions triggers, secrets, notifications, and troubleshooting. |
| [Performance](operations/performance.md) | Batch reads, caching, bounded concurrency, and measurement. |

### Reference

| Document | Purpose |
|---|---|
| [Button styles](reference/button-styles.md) | Rich button styles, row layouts, and callback-data naming. |

## Architecture at a glance

The system topology diagram lives in
[`pipelines/banning.md`](pipelines/banning.md).

Runtime starts with `uv run python -m tcbot`. The entry point loads the
configuration, starts the Flask health endpoint, builds the Telegram
application, connects PostgreSQL, applies Alembic migrations, seeds the
initial Owner, discovers and registers handlers, and starts webhook transport
when a public URL is available. Local development without a public URL falls
back to long polling.

User-facing messages are rich messages sent through the `messages/` helpers.
No parse mode is selected. Buttons are built in `modules/helper/buttons/` and
rendered as rich buttons, with the inline keyboard kept only as a fallback for
button cells that cannot be mapped. All user-facing wording comes from the
`i18n/` TOML catalogs, with `en-US` as the source of truth.

## Core ownership rules

- Keep command handlers in `tcbot/modules/`.
- Keep shared handler helpers in `tcbot/modules/helper/`.
- Keep conversation factories in `tcbot/modules/helper/pipelines/*_flow.py`.
- Keep database reads and writes behind `tcbot/database/*_db.py` helpers.
- Keep runtime utilities in `tcbot/utils/`.
- Keep configuration in `tcbot/__init__.py`; never read raw environment
  variables elsewhere.
- Keep secrets out of the repository and out of logs.

## Development commands

```bash
uv sync --frozen
uv run ruff format .
uv run ruff check --fix .
uv run pyright .
uv run pytest tests/ -q
uv run python -m tcbot
```

The project targets Python 3.14 and uses `uv` for dependency management.
