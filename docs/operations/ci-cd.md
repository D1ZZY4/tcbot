# CI/CD Workflows

This document describes all GitHub Actions workflows configured for the TCF Bot project.

For the user-facing CI/CD overview, see [`../../README.md`](../../README.md#development).
For the changelog of CI/CD additions, see
[`../../CHANGELOG.md`](../../CHANGELOG.md).

## Overview

The project uses 7 automated workflows for continuous integration, code quality, and maintenance:

1. **Lint (Ruff)** - Lint, format, and import check
2. **Lint (Pyright)** - Static type check
3. **Test (Pytest)** - Behavioral checks
4. **Auto-Fix Code Quality** - Automatically fix linting issues
5. **Dependency Updates** - Weekly dependency updates with auto-PR
6. **CodeQL** - Security analysis
7. **Run Bot** - Long-running bot runner with push-triggered handover, self-chaining, and cron fallback

---

## 1. Lint and Test (CI Gate)

Three workflows with identical triggers (push to `main`, `feat/**`,
`fix/**`; pull requests to `main`), one job each:

- **Lint (Ruff)** (`.github/workflows/lint-ruff.yml`): `uv run ruff format
  --check .`, `uv run ruff check .`, and `uv run python -c "import tcbot"`.
- **Lint (Pyright)** (`.github/workflows/lint-pyright.yml`): `uv run pyright`.
- **Test (Pytest)** (`.github/workflows/test-pytest.yml`): `uv run pytest tests/ -q`.

**What they share:**
- `uv sync --frozen` installs from the lockfile before every job.
- **Fails the PR** if any step exits with a non-zero code.
- Dummy but shape-valid `BOT_TOKEN`, `MONGODB_URI`, and `OWNER_ID` values
  (validated at import time, never connecting), so fork PRs without
  repository secrets still pass.

**Why this exists:**
The three workflows provide a repeatable CI result for formatting, lint,
types, imports, and behavioral checks. Whether they block merging depends
on the repository's branch protection settings.

---

## 2. Auto-Fix Code Quality

**File:** `.github/workflows/auto-fix.yml`

**Triggers:**
- Push to `main`, `feat/**`, `fix/**`
- Pull requests to `main`
- Weekly schedule (Monday 04:00 UTC)
- Manual dispatch
- Workflow run after `Lint (Ruff)` and `Lint (Pyright)` complete (waits for both lints before fixing)

**What it does:**
- Runs `uv run ruff format .` to auto-format code
- Runs `uv run ruff check --fix .` to auto-fix linting issues
- Runs `uv run pyright` and `uv run pytest tests/ -q` to capture type and test failures
- Sends remaining Ruff, Pyright, and Pytest errors to a free AI (GitHub Models `openai/gpt-4o-mini` via `GITHUB_TOKEN`, no billing) for a short fix summary; deterministic Ruff fixes are always applied, AI hints are advisory and included in the PR body and summary
- Creates or updates an `auto-fix/ruff` branch and pull request when fixes are
  found outside a pull-request run
- **Comments on PR** with fix suggestions (if PR) including Pyright counts
- Creates detailed summary of changes including Pyright, Pytest, and AI summary

**Benefits:**
- Reduces manual work for code style and catches type/test issues
- Consistent formatting across reviewed changes
- Free AI assists with Pyright/Pytest triage without extra secrets

**Example generated commit:**
```
chore: Auto-fix code quality issues

- Ruff format: 3 files
- Ruff check --fix: 5 files
- Pyright errors: 2
- AI assisted: 1

Auto-applied by GitHub Actions (Ruff deterministic + free AI for Pyright/Pytest)
```

---

## 3. Dependency Updates

**File:** `.github/workflows/dependency-update.yml`

**Triggers:**
- Weekly schedule (Monday 04:00 UTC)
- Manual dispatch

**What it does:**
- Runs `uv lock --upgrade` to update all dependencies
- Installs the updated lockfile and validates it (Ruff format/lint plus the
  `import tcbot` check, with dummy shape-valid environment values like
  the lint/test workflows above)
- Generates a professional PR title and body via a free AI (GitHub Models `openai/gpt-4o-mini` via `GITHUB_TOKEN`, no billing) from the lockfile diff; falls back to the static template when the model is unavailable
- **Auto-creates a PR** (`deps/auto-update-YYYYMMDD`, suffixed `-runNNN` on
  collision) labeled `dependencies` against `main`
- If the default token cannot open PRs (repository toggle off), the step
  retries once with `BOT_PAT` when that secret exists, then fails loud
  pointing at the exact toggle
- PR includes a diff of the lockfile changes
- **Sends Telegram notification** with result

**Benefits:**
- Regular dependency review with expert-level PR descriptions
- Less manual work for routine updates
- Telegram status notifications when configured

**Example PR:**
```
Title: chore(deps): bump ruff 0.12.1 -> 0.12.3

Body:
- Bump ruff 0.12.1 -> 0.12.3 for format speed
- No behavior change, import tcbot still passes

Review the dependency changes and CI results before merging.
```

---

## 4. CodeQL

**File:** `.github/workflows/codeql.yml`

**Triggers:**
- Push to `main`
- Pull requests to `main`
- Weekly schedule (Tuesday 15:38 UTC)

**What it does:**
- Runs GitHub's CodeQL security analysis on the `actions` and `python`
  languages with `build-mode: none` (pure source scan, no build step)
- Findings land under the repository Security tab

---

## 5. Run Bot

**File:** `.github/workflows/run-bot.yml`

**Triggers:**
- Self-dispatch (`workflow_dispatch`) from the previous run, for seamless chaining
- Cron schedule every 15 minutes as a resurrection fallback if the chain breaks
- Push to `main` touching runtime files (`tcbot/**`, `i18n/**`, `pyproject.toml`, `uv.lock`, `.python-version`, the workflow itself) for a rolling restart on the new commit

**What it does:**
- Runs the bot for a ~5 hour window per run (GitHub caps a job at 6h). When `WEBHOOK_URL` is set the bot uses webhook mode; otherwise it falls back to polling. `WEBHOOK_SECRET` is optional because the runtime generates one when absent
- **Rolling restart on runtime pushes:** a push to `main` that touches bot code, translations, dependencies, or the runner itself queues a successor run on the new commit, and the live run hands over to it: about every 2 minutes the watchdog compares its checkout SHA against the branch tip, and on a runtime diff it stops gracefully and exits, freeing the concurrency gate for the queued run. The new commit serves within minutes instead of waiting out the 5-hour window. Docs-only pushes never start a run and only move the live run's baseline. Schedule and handover runs keep queueing behind the live bot, so a cron tick can never terminate it. Three straight unreadable diffs also hand over rather than wait blind. Cancellation (manual or otherwise) and the window end share one bounded graceful shutdown (TERM trap with a 60 s wait), so logs and enforcement state are never cut mid-write
- **Self-chains:** roughly 10 minutes before the window ends (`HANDOVER_LEAD=600`), it dispatches the next run. The dispatch is retried up to 3 times (10s apart). This requires a repository secret `BOT_PAT` (a Personal Access Token with the `workflow` scope), because the built-in `GITHUB_TOKEN` cannot trigger workflows
- The cron schedule (every 15 minutes) acts as a resurrection fallback if the chain breaks or no PAT is configured. The `concurrency` group (`cancel-in-progress: false`) serializes runs: a cron tick while a run is active queues behind it instead of being discarded, so ticks can pile up behind a long holder
- A `concurrency` group (`tcf-bot-runner`, `cancel-in-progress: false`) prevents overlapping bot instances. This avoids duplicate update processing in polling mode and keeps webhook ownership unambiguous
- **Graceful stop before artifacts:** at the window end the bot gets SIGTERM (`uv run` forwards it to the child) and the script waits up to 60 s for exit before the scrub/upload steps, so the artifact keeps its final lines. The bot is backgrounded directly (`$!` stays a real child job) so the wait supervises the actual process; a stubborn process is left for runner teardown inside the 30 min post-window buffer
- Bot configuration comes from repository secrets (`BOT_TOKEN`, `MONGODB_URI`, `OWNER_ID`, `WEBHOOK_URL`, `WEBHOOK_SECRET`, etc.), plus the optional `BOT_PAT` for self-chaining. The push restart needs no extra secret: `cancel-in-progress: false` means the successor queues behind the live run, and the live run itself detects the runtime diff (self-preempt poll) and stops, freeing the gate
- **Log artifacts are scrubbed:** workflow logs and artifacts on a public repository are world-readable, so before the crash tail is printed or uploaded, token-shaped (`id:hash`) and URI-auth substrings are redacted with the same patterns as `error_reporter.py`. Message excerpts remain by design so crashes stay debuggable; artifacts are kept 7 days

---

## Workflow Dependencies

```
Lint (Ruff) + Lint (Pyright) + Test (Pytest)
    ↓
Pass: PR can merge / Fail: PR is blocked

Auto-Fix Code Quality
    ↓
Auto-fix branch and PR OR PR Comment (PR)

Dependency Updates
    ↓
Auto-create PR
    ↓
Telegram Notification

Run Bot (schedule / handover dispatch: queues behind the live run)
    ↓
Self-dispatch next run (~10 min before window ends)
    ↓
Cron fallback restarts if the chain breaks

Run Bot (push with runtime changes: queues a successor; the live run hands over within ~2 min)
```

---

## Secrets Required

Configure these in GitHub repository settings → Secrets:

| Secret | Purpose | Required |
|--------|---------|----------|
| `BOT_TOKEN` | Telegram bot token (bot runtime + notifications) | Yes |
| `MONGODB_URI` | MongoDB connection string for the bot runtime | Yes |
| `OWNER_ID` | Your Telegram user ID (initial owner + notifications) | Yes |
| `WEBHOOK_URL` | Public HTTPS URL for Telegram webhook (e.g. `https://your-domain.com`). When set, bot runs in webhook mode; absent means polling fallback | Recommended |
| `WEBHOOK_SECRET` | Secret token for `set_webhook` and `X-Telegram-Bot-Api-Secret-Token` validation. Auto-generated when omitted | Recommended |
| `API_ID` | Telegram API ID for mandatory MTProto lookups (get it at my.telegram.org). Without it the bot refuses to boot | Yes |
| `API_HASH` | Telegram API hash matching `API_ID`. Required together with `API_ID` | Yes |
| `BOT_PAT` | Personal Access Token with `workflow` scope, used by Run Bot to self-chain into the next run for seamless 24/7 coverage | Optional (recommended) |
| `GITHUB_TOKEN` | Auto-provided by GitHub Actions | Auto |

Without `BOT_PAT`, the Run Bot workflow cannot dispatch its own next run; it falls back to the every-15-minute cron resurrection schedule.

The Run Bot workflow forwards the full federation env surface as repository
secrets, so every runtime variable must be set there for the runner: `DB_NAME`,
`COMMUNITY_NAME`, `PREFIXES`, `MAIN_GROUP`, `MAIN_CHANNEL`, `EXTEND_GROUP`,
`PROOFS`, `LOGS`, `LOGS_ERRORS`, `APPEALS`, `LOG_LEVEL`, `PORT`, `REDIS_URL`,
`APPEAL_LOG_HANDLE`, `APPEAL_DISCUSSION_TOPIC`, `WARN_EXPIRY_DAYS`,
`WARN_LIMIT`, `FED_WARN_LIMIT`, `API_ID`, `API_HASH`,
`ALBUM_DEBOUNCE_SECONDS`, `MODULES_LOAD`, and
`MODULES_NO_LOAD`, alongside `BOT_TOKEN`, `MONGODB_URI`, `OWNER_ID`,
`WEBHOOK_URL`, and `WEBHOOK_SECRET`. `SYNC_INTERVAL_HOURS`, `CRON_SECRET`, and
the `COMMUNITY_*_URL` links are **not** forwarded by the runner: the sync sweep
and community URLs are not part of this transport.

---

## Notification Examples

### Dependency Update
```
Dependency Update - PASS

Dependencies updated
Result: PR created

View workflow
```

---

## Best Practices

### For Developers

1. Run the same checks locally before opening a pull request:
   `uv run ruff format --check .`, `uv run ruff check .`, and
   `uv run python -c "import tcbot"`.
2. Review auto-fix and dependency pull requests before merging them.
3. Treat Telegram notifications as status updates, not as a substitute for
   reviewing the workflow result.

### For Maintainers

1. **Monitor GitHub issues** - Auto-created issues need triage
2. **Review auto-fix pull requests** - Verify changes are correct
3. **Keep `BOT_PAT` valid** - An expired token breaks Run Bot self-chaining; the cron fallback still resurrects the bot, but with brief gaps
4. **Check workflow runs** - Weekly scheduled runs keep dependencies fresh

---

## Troubleshooting

### Telegram notifications not working
- Verify `BOT_TOKEN` and `OWNER_ID` secrets are set
- Verify bot can send messages to your user ID

### Auto-fix pull request not created
- Check branch protection rules allow bot commits
- Verify workflow has `contents: write` permission
- If the log says `GitHub Actions is not permitted to create or approve pull requests`, enable Settings → Actions → General → Workflow permissions → `Allow GitHub Actions to create and approve pull requests` (the fix branch is already pushed, so re-running or opening the PR manually recovers)

### Dependency PR not created
- Verify `pull-requests: write` permission
- Same repository toggle as above: without `Allow GitHub Actions to create and approve pull requests`, `gh pr create` fails even with the right permissions (the `deps/auto-update-*` branch is already pushed, so re-running or opening the PR manually recovers)

### Bot not staying online (Run Bot)
- Verify `BOT_TOKEN`, `MONGODB_URI`, and `OWNER_ID` secrets are set
- For seamless 24/7, set `BOT_PAT` (a PAT with the `workflow` scope) so the run can dispatch its successor; otherwise only the 15-minute cron fallback restarts it
- A `409 Conflict` from Telegram means two instances are polling at once; the `tcf-bot-runner` concurrency group should prevent this, so check for a stray manual run

### Bot restarted right after a push (Run Bot)
- Expected when the push touched runtime files: the live run detects the new commit and hands over on purpose so the new commit serves within minutes. Docs-only pushes never restart the bot
- If restarts flap on rapid successive pushes, the latest commit always wins; avoid pushing runtime fixes one line at a time during an incident

---

## Maintenance

### Weekly Tasks (Automated)
- Dependency updates (Monday 04:00 UTC)
- Code quality fixes (Monday 04:00 UTC)

### Manual Tasks
- Review and merge dependency update PRs
- Triage auto-created issues
- Keep `BOT_PAT` valid so Run Bot self-chaining stays seamless

---

The workflows documented here are the workflows currently present in
`.github/workflows/`. New automation should be documented here when it is
added.
