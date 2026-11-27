# TCF Bot documentation

This is the maintained documentation set for TCF Bot, the Python Telegram bot
for the Transsion Core Federation. Every page describes the behaviour in this
checkout. For the user-facing overview use the [root README](../README.md).

## Start here

| Audience | First page |
|---|---|
| Operator | [Setup](getting-started/setup.md), then [CI/CD](operations/ci-cd.md) and [Backup and restore](operations/backup-and-restore.md). |
| Moderator | [Commands](reference/commands.md), then the relevant [flow](flows/README.md). |
| Developer | [Architecture overview](architecture/overview.md), then [Database](architecture/database.md) and [Security](architecture/security.md). |
| Contributor | [CONTRIBUTING.md](../CONTRIBUTING.md) and [AGENTS.md](../AGENTS.md). |

## Documentation map

### Getting started

- [Setup](getting-started/setup.md) - prerequisites, configuration, local and Docker runs, health endpoints, first-run checklist.

### Architecture

- [Overview](architecture/overview.md) - repository layout, package ownership, startup, module discovery, handlers, helpers, utilities.
- [Database](architecture/database.md) - three schemas, async engine, table groups, schema objects, domain helpers, migrations, cache.
- [Security](architecture/security.md) - tiers, decorators, permissions, executor-versus-target checks, protected targets, demote gates, group isolation.
- [Runtime](architecture/runtime.md) - i18n, dispatch and breakers, transport budgets, logging and error reporting, tasks, update processing, workers, scheduler, pg_cron, cache mechanics.

### Flows

Every diagram lives in this section, which has its own
[index](flows/README.md). Each page is authoritative for one domain: entry,
state machine, database writes, Telegram delivery, failure paths, and exact names.

| Page | Covers |
|---|---|
| [System spine](flows/system.md) | Startup, update dispatch, authorization, persistence and transport boundary. |
| [Permissions](flows/permissions.md) | Tier gates, permission catalog, executor-versus-target checks, protected targets. |
| [Rate limiting](flows/ratelimit.md) | Throttles, Redis sliding window, circuit breakers, flood waits. |
| [Persistence](flows/persistence.md) | Transactions, enforcement ledger, retries, outbox, scheduler and pg_cron. |
| [Cache](flows/cache.md) | L1/L2, single-flight, generation and epoch guards, tombstones, FIFO queue. |
| [Transport](flows/transport.md) | Rich send and edit, keyboard conversion, callbacks, error reports, links. |
| [Extraction and user data](flows/extraction-user-data.md) | Target resolution, MTProto fallback, identity classification, mention cache. |
| [Banning](flows/banning.md) | Federation ban, re-ban confirmation, proof, dual gate, decision write, summary. |
| [Unbanning](flows/unbanning.md) | Fail-closed demote, atomic revoke, per-group delivery, appeal slot, repair. |
| [Kicking](flows/kicking.md) | Current-chat ban and rejoin, audit row, reconcile repair. |
| [Muting](flows/muting.md) | Duration parsing, timed state machine, revoke, join and connect replay. |
| [Warning](flows/warning.md) | Thresholds, staff exemption, automatic ban, conservative clearing. |
| [Proof](flows/proof.md) | Media filter, debounce and flush claim, upload chunking, archive. |
| [Appeals](flows/appeals.md) | Deep link and group tag, atomic claim, reviewer windows, durable card edits. |
| [Connection](flows/connection.md) | Connect, bounded replay, join enforcement, disconnect, primary groups. |
| [Roles](flows/roles.md) | Promotion, queued request, demotion, atomic ownership transfer. |
| [Community rules](flows/rules.md) | Editor, publication lease, acknowledgment, shared picker. |
| [Check and statistics](flows/statistics.md) | Drill-down trees, pagination, batched reads, access tiers. |

### Features

- [Language](features/language.md) - locale resolution, TOML catalog, selection flow.
- [Community rules](features/rules.md) - editor, publication, acknowledgement, shared picker.

### Reference

- [Commands](reference/commands.md) - every command, alias, access tier, and origin rule.
- [Callbacks and states](reference/callbacks.md) - exhaustive callback and `WAITING_*` registry plus the payload grammar.
- [Buttons](reference/buttons.md) - every keyboard builder, emitted callback, color, label key, and layout rule.
- [Configuration](reference/configuration.md) - every environment variable, default, and validation rule.

### Operations

- [Backup and restore](operations/backup-and-restore.md) - PostgreSQL dump and restore procedures.
- [CI/CD](operations/ci-cd.md) - the seven GitHub Actions workflows and their secrets.
- [Performance](operations/performance.md) - bounded concurrency, batching, cache, and measurement.

### Releases

Published release notes are immutable history under [v7.1.0](releases/v7.1.0.md).
The root [CHANGELOG.md](../CHANGELOG.md) holds the unreleased section and the release index.

## Architecture at a glance

`uv run python -m tcbot` loads configuration, starts the Flask keep-alive server,
creates the single Kurigram client, registers handlers,
connects PostgreSQL and applies Alembic migrations, seeds the initial Owner,
registers infrastructure destinations, connects Redis and MTProto, starts the
scheduler, and then runs the Kurigram long-polling loop. The exact
order is in [system.md](flows/system.md).

Telegram updates pass through a command or callback filter and tier decorators,
then a handler that delegates persistence to `tcbot/database/` helpers and
multi-step work to a domain-named pipeline module, and a rich-message reply.
Only decorated handlers are throttled; there is no global rate limiter.
Proof media is uploaded to the configured evidence destination before the
decision is filed; federation-wide enforcement fan-out happens after the decision
commits to PostgreSQL. Telegram work goes through the bounded `fan_out()`
dispatcher and the Telegram circuit breaker; unfinished per-group deliveries are
retried by the enforcement worker.

## Ownership rules

- Commands and callbacks live in `tcbot/modules/`; shared helpers in `tcbot/modules/helper/`.
- Conversation factories live in `tcbot/modules/helper/pipelines/` as domain-named
  `*_executor.py`, `*_conversation.py`, `*_actions.py`, `*_steps.py`, `*_panels.py`, or plain modules.
- Database reads and writes live in `tcbot/database/*_db.py` helpers.
- Runtime utilities live in `tcbot/utils/`; configuration in `tcbot/__init__.py`.
- User-facing wording lives in `i18n/<locale>/*.toml`, never hardcoded in Python
  outside sanctioned audit, staff, and infrastructure messages.
- Secrets stay out of the repository and out of logs.

## Validation commands

```bash
uv sync --frozen
uv run ruff format --check .
uv run ruff check .
uv run pyright .
uv run pytest tests/ -q
uv run python -m tcbot
```

The project targets Python 3.14 and uses `uv` for every dependency and run command.
