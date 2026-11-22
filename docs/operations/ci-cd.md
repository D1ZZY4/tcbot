# CI/CD workflows

This page documents the GitHub Actions workflows in `.github/workflows/`. They
cover linting, type checking, tests, security scanning, automated fixes,
dependency updates, and the 24/7 bot runner.

Related pages: [setup](../getting-started/setup.md) and
[utilities](../architecture/utilities.md).

## Workflow inventory

| Workflow | File | Triggers | Purpose |
|---|---|---|---|
| Lint (Ruff) | `lint-ruff.yml` | Push and PR on main, feat/**, fix/** | Format check, lint, file-size budget, import check. |
| Lint (Pyright) | `lint-pyright.yml` | Same | Static type check. |
| Test (Pytest) | `test-pytest.yml` | Same | PostgreSQL tests first, then the rest in parallel with coverage. |
| CodeQL | `codeql.yml` | Push and PR on main, weekly schedule | Security analysis for Python and Actions. |
| Auto-Fix Code Quality | `auto-fix.yml` | Push, PR, dispatch, weekly schedule, and completion of the lint workflows | Applies Ruff fixes and opens or updates an auto-PR. |
| Dependency Updates | `dependency-update.yml` | Weekly schedule and dispatch | Upgrades `uv.lock` and opens a dependency PR. |
| TCF Bot 24/7 Runner | `run-bot.yml` | Dispatch, every 15 minutes, and runtime pushes | Runs the bot with a watchdog and self-chaining handover. |

## Lint and type workflows

All three validation workflows install Python 3.14, install `uv`, run
`uv sync --frozen`, and use dummy values for `BOT_TOKEN`, `DATABASE_URL`, and
`OWNER_ID` so importing the package does not require real secrets.

- Ruff runs `ruff format --check .` and `ruff check .`. It also enforces the
  1,000-line file budget across `tcbot/` and checks that `import tcbot` works.
- Pyright runs `uv run pyright`.
- Pytest runs the `postgres`-marked group serially against a PostgreSQL 16
  service, then the remaining tests with `-n auto` and coverage. A Redis 7
  service supports the cache tests. Database and Redis tests skip when their
  service is unavailable.

The test suite sets dummy environment values in `tests/conftest.py` at
collection time and uses the `test` schema only. A collection hook marks any
test that requests the shared PostgreSQL fixtures so xdist cannot strand it on
a worker that is not allowed to own that schema.

## Auto-fix workflow

`auto-fix.yml` runs Ruff format and `ruff check --fix`, captures Pyright and
Pytest output, and uses free GitHub Models inference for a short fix summary
when issues remain. It targets the fixed branch `auto-fix/ruff` and serializes
runs with concurrency group `auto-fix-ruff`. On pushes it opens or updates a PR;
on PR events it posts a comment with the commands to apply the deterministic
fixes locally.

The workflow needs `contents: write`, `pull-requests: write`, and `models: read`.
If `gh pr create` reports that GitHub Actions is not permitted to create
pull requests, enable the repository toggle under Settings, Actions, General,
Workflow permissions. The branch is already pushed, so the PR can be opened
manually after flipping the toggle.

## Dependency update workflow

`dependency-update.yml` copies `uv.lock`, runs `uv lock --upgrade`, and opens a
PR on branch `deps/auto-update-<date>` when the lock changed. It validates with
`ruff format --check`, `ruff check`, and `import tcbot`, then generates a
Conventional Commit title and body through GitHub Models with a static
fallback. It retries PR creation with `BOT_PAT` when `github.token` lacks
permission, and sends a plain HTML Telegram notification to `OWNER_ID`.

## 24/7 runner

`run-bot.yml` is the production hosting path. Key behavior:

- A 5-hour runtime window with a 10-minute handover lead, inside a 330-minute
  job timeout.
- A concurrency group named `tcf-bot-runner` with `cancel-in-progress: false`,
  so cron and handover runs queue behind the live run instead of killing it.
- A watchdog restarts the bot if it dies, with linear backoff capped at five
  minutes. Five deaths within ten minutes abort the run and rely on the
  15-minute cron for recovery.
- Self-preempt polls the branch about every two minutes. A runtime push
  (under `tcbot/`, `i18n/`, `pyproject.toml`, `uv.lock`, `.python-version`, or
  this workflow) stops the live run gracefully so the queued successor serves
  the new commit. Docs-only pushes do not restart the bot.
- With `BOT_PAT`, the run dispatches its successor shortly before handover,
  retrying three times. Without it, the 15-minute cron provides restarts.
- Runtime secrets are passed as workflow environment variables. Logs are
  scrubbed of token and URI-shaped credentials before being uploaded as a
  public artifact, and a crash signature check saves the last 120 lines.

## Required secrets and variables

| Secret | Used by | Purpose |
|---|---|---|
| `BOT_TOKEN`, `DATABASE_URL`, `OWNER_ID` | Runner, notifications | Runtime credentials. |
| `API_ID`, `API_HASH`, `MTPROTO_SESSION` | Runner | MTProto identity lookups. |
| `PROOFS`, `LOGS`, `LOGS_ERRORS`, `APPEALS`, `MAIN_GROUP`, `MAIN_CHANNEL` | Runner | Infrastructure destinations. |
| `DB_SCHEMA`, `DB_POOL_SIZE`, `DB_MAX_OVERFLOW`, `REDIS_URL`, `PG_CRON_ENABLED` | Runner | Database and cache configuration. |
| `WEBHOOK_URL`, `WEBHOOK_SECRET`, `PORT`, `BIND_HOST` | Runner | Webhook transport. |
| `WARN_LIMIT`, `WARN_EXPIRY_DAYS`, `FED_WARN_LIMIT`, `PROMOTION_REQUEST_TTL_DAYS` | Runner | Moderation policy. |
| `PREFIXES`, `COMMUNITY_NAME`, `LOG_LEVEL`, `ALBUM_DEBOUNCE_SECONDS` | Runner | Behavior and display. |
| `MODULES_LOAD`, `MODULES_NO_LOAD`, `SENTRY_DSN` | Runner | Optional features. |
| `BOT_PAT` | Runner, dependency updates | Self-chain dispatch and PR fallback. |

`GITHUB_TOKEN` and `secrets.GITHUB_TOKEN` are provided automatically.

## Troubleshooting

- A dead runner usually means a bad secret or a database outage. Check the
  scrubbed `bot.log` artifact and the startup stage in the fatal output.
- A PR creation failure is a workflow permission toggle, not a code defect.
- A skipped database test means no server was reachable; check the service
  container and `TCBOT_TEST_DATABASE_URL`.
- The runner ignores docs-only pushes by design; a bot restart needs a runtime
  file change or a manual dispatch.

## Validation hints

Run the same commands locally before pushing:

```bash
uv run ruff format --check .
uv run ruff check .
uv run pyright .
uv run pytest tests/ -q
```
