# TCF Bot

Telegram federation moderation bot for the Transsion Core Federation community. One bot enforces moderation decisions across all connected groups: federation bans with proof, appeals, staff roles, and audit logging.

## Requirements

- Python 3.14 and `uv`
- A Telegram bot token from BotFather
- PostgreSQL (a local server or a managed instance)
- Redis is optional. Without it the bot uses in-process caching.

## Quick Start

```bash
cp config.env.example config.env
uv sync --frozen
uv run python -m tcbot
```

Fill in at least `BOT_TOKEN`, `OWNER_ID`, `DATABASE_URL`, `PROOFS`, `API_ID`, and `API_HASH` in `config.env` before running. A ban needs a destination for its evidence, so boot refuses without `PROOFS`. Never commit that file. The full variable list is in [`config.env.example`](config.env.example) and [`docs/getting-started/setup.md`](docs/getting-started/setup.md).

Run from a checkout with `uv sync --frozen`, or use the container image. Non-editable wheels are not a supported install path: the locale catalogs, Alembic scripts, and schema SQL are resolved relative to the project root and are not packaged into a wheel.

## What It Does

- **Federation bans with proof.** `/tcban` collects proof media or text first, then enforces across every connected group and stores the proof reference for review.
- **Appeals.** Banned users submit through a deep link in bot DM or with `#appeal` in the main group. Staff approve or reject from review cards posted in the main group.
- **Standard moderation.** `/tckick`, `/tcmute`, `/tcwarn`, `/tcunban`, and `/check` cover kick, mute, warn, unban, and ban-history lookup. Warn thresholds can trigger an automatic federation ban.
- **Staff roles.** Owner, Admin, Developer, and Moderator hierarchy with promotion requests, demotion, and automatic demotion before a staff member is banned, kicked, or muted.
- **Connected groups.** Groups and forums opt in with `/tcconnect`. Multi-group actions fan out with bounded concurrency so one failing group does not abort the rest.
- **Audit trail.** Moderation, appeal, role, and error reports go to the configured log destinations.

## Commands

| Command | Purpose |
|---|---|
| `/tcban` (alias `/tcb`) | Federation-wide ban with required photo/video proof. |
| `/tcunban` (alias `/tcunb`) | Lift an active federation ban across all groups. |
| `/tckick` (alias `/tck`) | Remove a user from the current group only. |
| `/tcmute` (alias `/tcm`), `/tcunmute` | Restrict or restore messaging across all groups, optionally timed (`1m`, `15m`, `2h`, `7d`, `1w`, `3mo`, up to `366d`). |
| `/tcwarn` (alias `/tcw`), `/tcunwarn`, `/warns`, `/resetwarns` | Per-group warnings; hitting the limit triggers an automatic federation ban. |
| `/check`, `/checkme` | Ban-history lookup for a target or for yourself, with appeal links. |
| `/tcconnect`, `/tcdisconnect`, `/rmtc`, `/tcgroups` | Connect or remove groups and list the federation roster. |
| `/tcpromote`, `/tcsetrole`, `/tcdemote`, `/transferowner` | Manage Owner, Admin, Developer, and Moderator roles, including changing an existing role. |
| `/tcstats` | Federation statistics with drill-down views. |
| `/tcrules` (alias `/tcrls`), `/rules` | Staff rule editor and the read-only community rules menu. |
| `/tcpromoterequests`, `/tcpromotelist` | Submit an Admin promotion request and list the pending ones. |
| `/help`, `/start` | Topic help and the start menu. |
| `/language` | Per-user or per-group interface language. |
| `/leaveall`, `/cleanup` | Owner-only mass leave and staff-only cleanup of dead group records. |
| `/tcrepair` (alias `/tcr`) | Staff-only list of unsettled enforcement runs and re-drive of their failed groups. |
| `/tcforget` (alias `/tcf`) | Owner-only account erasure request for the next erasure sweep. |
| `/tcbroadcast` | Staff-only broadcast to every connected group. |
| `/ping`, `/speedtest` | Latency check and throughput measurement; `/st full` uses a larger sample. |

Appeals are submitted by the banned user in bot DM through a deep link, or with `#appeal` in the main group. Command prefixes are configurable (default `/`, `!`, `.`).

## Configuration

Only six values are required. Everything else has a working default.

| Variable | Required | Description |
|---|---:|---|
| `BOT_TOKEN` | Yes | Bot token from BotFather. |
| `OWNER_ID` | Yes | Telegram user ID seeded as the initial Owner. |
| `DATABASE_URL` | Yes | PostgreSQL connection string. The bot applies its schema migrations at startup. |
| `PROOFS` | Yes | Ban proof media destination; boot refuses without a negative group or channel chat ID. |
| `API_ID` | Yes | Telegram API ID for MTProto identity lookups; boot refuses without it. |
| `API_HASH` | Yes | Telegram API hash matching `API_ID`; boot refuses without it. |


> [!IMPORTANT]
> Never commit real secrets. Keep `BOT_TOKEN`, `DATABASE_URL`, passwords, secrets, and private chat IDs out of the repository; use the platform secret manager on hosted deployments.

<details>
<summary>Full variable reference (all settings in <code>config.env.example</code>)</summary>

### Core

| Variable | Required | Default | Description |
|---|---|---|---|
| `BOT_TOKEN` | Yes | - | Bot token from BotFather. |
| `OWNER_ID` | Yes | - | Telegram user ID seeded as the initial Owner. |
| `DATABASE_URL` | Yes | - | PostgreSQL connection string. |
| `COMMUNITY_NAME` | No | `Bot` | Display name used in bot messages and logs. |
| `PREFIXES` | No | `["/", "!", "."]` | Python-style list of command prefixes. |
| `PORT` | No | `5000` | Flask health-server port (`1`-`65535`); `auto` or invalid values fall back to `5000`. |
| `BIND_HOST` | No | `0.0.0.0` | Listener interface; set `127.0.0.1` behind a local reverse proxy. |
| `LOG_LEVEL` | No | `INFO` | One of `NOTSET`, `DEBUG`, `INFO`, `WARNING`, `WARN`, `ERROR`, `CRITICAL`, `FATAL`. |

### Federation chats

| Variable | Required | Description |
|---|---|---|
| `MAIN_GROUP` | Usually | Main community group or forum (negative chat ID). |
| `MAIN_CHANNEL` | For rules | Main community channel (negative chat ID); the publication target for rules. |
| `INFRA_CHAT_IDS` | No | Extra deployment-owned chat IDs refused by the connect paths; list or CSV, negative IDs only. |

### Logs, proofs, and appeals

Chat destinations accept a chat ID or a `chat_id/thread_id` pair.

| Variable | Required | Description |
|---|---|---|
| `PROOFS` | Yes | Ban proof media destination; boot refuses without a negative group or channel chat ID. |
| `LOGS` | Recommended | Audit-log destination for bans, unbans, appeals, and admin actions. The bot boots without it, but every audit post then fails. |
| `LOGS_ERRORS` | Recommended | Error-report destination; when empty, reports fall back to the owner DM instead of being dropped. |
| `APPEALS` | For appeals | Submitted-appeal record destination (channel, group, or forum thread as `chat_id` or `chat_id/thread_id`; also receives a copy of every review card). |

### Moderation thresholds

| Variable | Default | Description |
|---|---|---|
| `WARN_LIMIT` | `3` | Per-group warns triggering auto-ban (minimum `1`, fires at or above the limit). |
| `FED_WARN_LIMIT` | `0` (disabled) | Federation-wide warns triggering auto-ban. |
| `WARN_EXPIRY_DAYS` | `0` (disabled) | Days after which a warning stops counting towards the auto-ban threshold. The history is kept. |

### Timeouts, cache, and modules

| Variable | Default | Description |
|---|---|---|
| `ALBUM_DEBOUNCE_SECONDS` | `4` | Proof silence window before the ban executor runs (or tap Done to run at once). |
| `PROMOTION_REQUEST_TTL_DAYS` | `7` | Days a pending Admin promotion request stays open before it is marked expired; `0` disables expiry. |
| `REDIS_URL` | empty (L1 only) | Optional Redis URL for the shared L2 cache. Without it the bot uses the in-process cache. |
| `DB_POOL_SIZE` | `5` | PostgreSQL connection pool size. Keep the total with `DB_MAX_OVERFLOW` within the connection limit the database grants. |
| `DB_MAX_OVERFLOW` | `5` | Extra connections the pool may open under load. |
| `DB_SCHEMA` | `public` | PostgreSQL schema the bot reads and writes. The project uses `public` for the deployment, `test` for the integration tests, and `development` for a developer. |
| `PG_CRON_ENABLED` | `false` | Let pg_cron run the pure-database expiry, role-expiry, and stuck-enforcement sweeps. Requires the extension; otherwise APScheduler keeps them. |
| `MODULES_LOAD` | empty (all) | Allowlist of modules to load exclusively. |
| `MODULES_NO_LOAD` | empty | Denylist of modules to skip. |

### Transport

| Variable | Description |
|---|---|
| `API_ID` | Required: Telegram API ID for MTProto identity lookups; boot refuses without it. |
| `API_HASH` | Required: Telegram API hash matching `API_ID`; never commit the real value. |
| `MTPROTO_SESSION` | Namespace for the shared MTProto session in PostgreSQL (default `tcbot_mtproto`). |
| `SENTRY_DSN` | Optional Sentry DSN for error monitoring; empty disables monitoring. |

### Community links

The Additional Links menu derives its buttons from `MAIN_CHANNEL`, `MAIN_GROUP`,
`LOGS`, and `APPEALS` through Telegram `get_chat`: a chat username becomes a
`t.me` link, otherwise its invite link is used, and a chat with neither drops
its button. No static community URL variables remain. See
[Community rules](docs/features/rules.md) for the rules editor and channel
publication.

</details>

## Running

Local development always uses Kurigram long polling; no public URL or webhook is needed:

```bash
uv run python -m tcbot
```

With Docker Compose (bot plus local PostgreSQL and Redis):

```bash
docker compose up --build
```

The compose setup reads `.env`, so copy `config.env.example` to `.env` first. Details are in [`docs/getting-started/setup.md`](docs/getting-started/setup.md).


> [!CAUTION]
> Never run two live bot instances with the same token (for example polling locally while polling mode is deployed). The transports fight over updates and Telegram reports `Conflict` errors.

One pitfall to avoid: committing `config.env` with real values because local testing worked. Keep it untracked and put production values in the host secret manager instead.

## Deployment

Run exactly one live instance per token on exactly one target below. Every target launches the bot module with `uv run`; hosted examples pin the lockfile with `--frozen`, and the container image also enables the `observability` extra.

<details>
<summary>GitHub Actions automation (lint, auto-fix, dependencies, CodeQL)</summary>

Seven CI workflows run automatically. The lint, type-check, test, auto-fix, dependency-update, and CodeQL workflows need no repository secrets (validation steps use dummy values, so fork PRs work too). The 24/7 Run Bot workflow is the exception: it needs the deployment secrets listed in the next section. The Python workflows set up Python 3.14 with cached `uv`; CodeQL uses `build-mode: none` and needs no Python or `uv` setup.

- **Lint (Ruff)** (`lint-ruff.yml`), **Lint (Pyright)** (`lint-pyright.yml`), **Test (Pytest)** (`test-pytest.yml`): on push to `main`/`feat/**`/`fix/**` and PRs to `main`. Run `ruff format --check` + `ruff check` + the `import tcbot` check, `pyright`, and two Pytest passes respectively: a serial `pytest tests/ -q -m postgres` pass, then `pytest tests/ -q -m "not postgres" -n auto --cov=tcbot --cov-branch --cov-append`. Fail the PR subject to branch protection.
- **Auto-Fix** (`auto-fix.yml`): same push/PR triggers plus weekly Monday 04:00 UTC and manual dispatch. Runs `ruff format` + `ruff check --fix`; outside a PR it force-pushes the fixed `auto-fix/ruff` branch and opens a PR, on a PR it comments the local fix commands instead. Needs `contents: write` + `pull-requests: write`.
- **Dependency Updates** (`dependency-update.yml`): weekly Monday 04:00 UTC and manual dispatch. Runs `uv lock --upgrade`, validates with Ruff plus the import check, then opens a `deps/auto-update-YYYYMMDD` PR labeled `dependencies` against `main` (no-op when the lockfile is unchanged). Sends the owner a Telegram status DM when `BOT_TOKEN`/`OWNER_ID` secrets exist, silently skips otherwise.
- **CodeQL** (`codeql.yml`): on push/PR to `main` plus weekly Tuesday 15:38 UTC. Scans the `actions` and `python` languages with `build-mode: none`; findings land under the repository Security tab.
- **Run Bot** (`run-bot.yml`): self-chaining 24/7 runner with Kurigram long polling, a watchdog, and a 15-minute cron resurrection fallback.

Mirror the gate locally before pushing: `uv run ruff format --check .`, `uv run ruff check .`, the 1000-line file-size budget over `tcbot/`, and `uv run python -c "import tcbot"`. Full reference: [`docs/operations/ci-cd.md`](docs/operations/ci-cd.md).
</details>

<details>
<summary>GitHub Actions 24/7 runner (self-chaining)</summary>

`.github/workflows/run-bot.yml` runs the bot in 5-hour windows (GitHub hard-caps a job at 6 h) with a crash watchdog, a handover dispatch about 10 minutes before the window ends, and a `*/15` cron resurrection fallback. A push to `main` touching bot code, translations, dependencies, or the runner itself queues a successor run and the live bot hands over gracefully within minutes; docs-only pushes never restart the bot.

2. For gap-free chaining add `BOT_PAT`: a Personal Access Token with the `workflow` scope. Without it only the 15-minute cron restarts the bot.
3. Actions → "TCF Bot - 24/7 Runner" → Run workflow (or wait for the schedule).
4. Verify in the run logs (`Bot started`, `subsystems ready`); crash tails ship as credential-scrubbed artifacts kept 7 days.

Fail-fast guard: 5 deaths within 10 minutes aborts the run (usually bad config); the cron recovers after you fix secrets. Full reference: [`docs/operations/ci-cd.md`](docs/operations/ci-cd.md). Respect GitHub Actions usage limits and Terms of Service; this runner is a community convenience, not a hosting SLA.
</details>

<details>
<summary>Docker and Docker Compose</summary>

1. `cp config.env.example .env` and set at least `BOT_TOKEN`, `OWNER_ID`, `DATABASE_URL=postgresql://tcbot:tcbot@postgres:5432/tcbot`, `PROOFS`, `API_ID`, `API_HASH`, and `REDIS_URL=redis://redis:6379/0`.
2. `docker compose up --build` (bot plus `postgres:16-alpine` plus `redis:7-alpine`, each with health checks; the bot waits for both databases).
3. Verify: `curl localhost:${PORT:-5000}/health` returns subsystem JSON with HTTP 200.

Single image without compose: `docker build -t tcf-bot .` then `docker run --env-file .env -p ${PORT:-5000}:${PORT:-5000} tcf-bot` (image command is `uv run --frozen --extra observability python -m tcbot`). Point PostgreSQL/Redis at reachable hosts.
</details>

<details>
<summary>Heroku (container stack, no Procfile needed)</summary>

The repository ships no `Procfile`; deploy the existing `Dockerfile` through the container registry.

1. `heroku create <app> && heroku stack:set container --app <app>` (or set the stack in Dashboard → Settings).
3. `heroku container:push worker --app <app> && heroku container:release worker --app <app>`.
4. `heroku ps:scale worker=1 --app <app>` and verify with `heroku logs --tail --app <app>`.

Heroku assigns `PORT` automatically and the bot reads it from the environment. Keep exactly one `worker` dyno per token.
</details>

<details>
<summary>VPS with systemd (Ubuntu/Debian)</summary>

1. Install Python 3.14 and `uv`, then `git clone <repo-url> /opt/tcf-bot && cd /opt/tcf-bot && uv sync --frozen`.
2. Create `/opt/tcf-bot/config.env` with `BOT_TOKEN`, `OWNER_ID`, `DATABASE_URL` (a managed instance with the VPS IP allowlisted, or self-hosted PostgreSQL), `PROOFS`, and `API_ID`/`API_HASH` for MTProto lookups, mode `0600`.
3. Install this unit as `/etc/systemd/system/tcf-bot.service` (adjust the `uv` path from `which uv`):

```ini
[Unit]
Description=TCF Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=tcfbot
WorkingDirectory=/opt/tcf-bot
EnvironmentFile=/opt/tcf-bot/config.env
ExecStart=/usr/local/bin/uv run --frozen python -m tcbot
Restart=on-failure
RestartSec=30

[Install]
WantedBy=multi-user.target
```

4. `systemctl daemon-reload && systemctl enable --now tcf-bot && journalctl -u tcf-bot -f`.
</details>

<details>
<summary>Windows Server over RDP</summary>

1. RDP in, install Python 3.14 (add to PATH) and `uv` (`irm https://astral.sh/uv/install.ps1 | iex`), then `git clone <repo-url> C:\tcf-bot` and `uv sync --frozen` inside it.
2. Create `C:\tcf-bot\config.env` with `BOT_TOKEN`, `OWNER_ID`, `DATABASE_URL`, `PROOFS`, `API_ID`, and `API_HASH`; restrict it to the service account via file ACLs.
3. Verify once interactively: `uv run python -m tcbot` (expect `subsystems ready`, `Ctrl+C` to stop).
4. Persist with Task Scheduler: trigger "At startup", action `uv.exe run --frozen python -m tcbot` with start-in `C:\tcf-bot`, "Run whether user is logged on or not", "If the task fails, restart every 1 minute". Prefer a dedicated service account, never an admin's personal session.
</details>

## Health Check

The Flask keep-alive server binds to `${BIND_HOST}:${PORT}` (`BIND_HOST` defaults to `0.0.0.0`; the port defaults to `5000` on unset, invalid, or out-of-range values).

- `GET /` returns `OK` for uptime monitors.
- `GET /health` returns subsystem status (database, Redis, scheduler, circuit breakers) as JSON, with HTTP 503 while degraded.

> [!TIP]
> Point uptime monitors at `GET /health`: the 503 status tells load balancers and watchdogs the instance needs attention without reading the body.

## Troubleshooting

- `BOT_TOKEN`, `OWNER_ID`, `DATABASE_URL`, `PROOFS`, `API_ID`, or `API_HASH` errors on startup: the bot fails fast on missing identity, database, evidence, or MTProto settings. Set them in `config.env` or the host secret manager.
- PostgreSQL connection failures: check the URL, network access, the host firewall, and the credentials.
- `GET /health` returns 503: the database, scheduler, or a circuit breaker is degraded; read the JSON body to see which one. Redis is reported as `disabled`, `unknown`, `ok`, or `error` but does not change the status code, because the cache is optional.

## Development

```bash
uv run ruff format --check .
uv run ruff check .
uv run pyright .
uv run python -m compileall -q tcbot
uv run python -c "import tcbot"
git diff --check
```

`pyproject.toml` targets Python 3.14 with line length 88. Dependencies install from `uv.lock` via `uv sync --frozen`. CI runs lint, auto-fix PRs, weekly dependency updates, CodeQL, and a long-running bot runner; see [`docs/operations/ci-cd.md`](docs/operations/ci-cd.md). Contribution workflow and review checklist are in [`CONTRIBUTING.md`](CONTRIBUTING.md).

## Documentation

- [Setup guide](docs/getting-started/setup.md) and [Configuration reference](docs/reference/configuration.md).
- [Architecture overview](docs/architecture/overview.md): startup flow, package ownership, and service boundaries.
- [Database layer](docs/architecture/database.md) and [Security model](docs/architecture/security.md).
- [Flow index](docs/flows/README.md): 18 full domain flows, starting with the [system spine](docs/flows/system.md).
- [Commands](docs/reference/commands.md) and [Callbacks](docs/reference/callbacks.md): stable references.
- [Documentation index](docs/README.md): the complete map.
- [Project guide](AGENTS.md): contributor and maintainer rules.

## Repo Activity

<details>
<summary>Contribution activity graph</summary>

Contribution, issue, and pull request activity, rendered by Repobeats.

![Repobeats analytics image](https://repobeats.axiom.co/api/embed/1a7b88805412c20305e8076a29a737330bae83ec.svg "Repobeats analytics image")

</details>

## License

Copyright © 2024-2026 Transsion Core, Dizzy, Ave Labs. Licensed under the Server Side Public License, Version 1.

See `LICENSE` for details.
