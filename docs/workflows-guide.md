# GitHub Workflows Documentation

This document describes all GitHub Actions workflows configured for the TCF Bot project.

For user-facing overview of CI/CD, see [`../README.md`](../README.md#cicd--automation). For contributor commit and PR guidance, see [`../AGENTS.md`](../AGENTS.md#commit-and-pull-request-guidance). For changelog of CI/CD additions, see [`../CHANGELOG.md`](../CHANGELOG.md).

## Overview

The project uses 4 automated workflows for continuous integration, code quality, and maintenance:

1. **Auto-Fix Code Quality** - Automatically fix linting issues
2. **Dependency Updates** - Weekly dependency updates with auto-PR
3. **CodeQL** - Security analysis
4. **Run Bot** - Self-chaining 24/7 long-polling runner

---

## 1. Auto-Fix Code Quality

**File:** `.github/workflows/auto-fix.yml`

**Triggers:**
- Push to `main`, `feat/**`, `fix/**`
- Pull requests to `main`
- Weekly schedule (Monday 04:00 UTC)
- Manual dispatch

**What it does:**
- Runs `ruff format .` to auto-format code
- Runs `ruff check --fix .` to auto-fix linting issues
- **Auto-commits fixes** to the branch (if not a PR)
- **Comments on PR** with fix suggestions (if PR)
- Creates detailed summary of changes

**Benefits:**
- Zero manual intervention for code style
- Consistent formatting across all commits
- Catches common issues automatically

**Example Auto-Commit:**
```
chore: Auto-fix code quality issues

- Ruff format: 3 files
- Ruff check --fix: 5 files

Auto-applied by GitHub Actions
```

---

## 2. Dependency Updates

**File:** `.github/workflows/dependency-update.yml`

**Triggers:**
- Weekly schedule (Monday 04:00 UTC)
- Manual dispatch

**What it does:**
- Runs `uv lock --upgrade` to update all dependencies
- Installs updated dependencies
- **Auto-creates PR** with dependency updates
- PR includes diff of changes
- **Sends Telegram notification** with result

**Benefits:**
- Always up-to-date dependencies
- Zero manual work for routine updates
- Immediate notification of breaking changes

**Example PR:**
```
Title: chore: Auto-update dependencies

Body:
## Automated Dependency Update

This PR updates project dependencies to their latest compatible versions.

### Changes
- python-telegram-bot: <old> → <new>
- motor: <old> → <new>

Safe to merge with new versions.
```

---

## 3. CodeQL

**File:** `.github/workflows/codeql.yml`

**Triggers:**
- Push to `main`
- Pull requests to `main`
- Weekly schedule

**What it does:**
- Runs GitHub's security analysis
- Scans for vulnerabilities
- Checks for common security issues

---

## 4. Run Bot

**File:** `.github/workflows/run-bot.yml`

**Triggers:**
- Self-dispatch (`workflow_dispatch`) from the previous run, for seamless chaining
- Cron schedule every 30 minutes as a resurrection fallback if the chain breaks

**What it does:**
- Runs the bot via long polling for a ~5 hour window per run (GitHub caps a job at 6h)
- **Self-chains:** roughly 15 minutes before the window ends, it dispatches the next run so coverage is continuous. This requires a repository secret `BOT_PAT` (a Personal Access Token with the `workflow` scope), because the built-in `GITHUB_TOKEN` cannot trigger workflows
- The cron schedule acts as a resurrection fallback that restarts the bot if the chain ever breaks or no PAT is configured
- A `concurrency` group (`tcf-bot-runner`, `cancel-in-progress: false`) ensures only one bot instance runs at a time, with at most one queued to take over seamlessly. Long polling allows only one active instance; a second would make Telegram return `409 Conflict`
- Bot configuration comes from repository secrets (`BOT_TOKEN`, `MONGODB_URI`, `OWNER_ID`, etc.), plus the optional `BOT_PAT` for self-chaining

---

## Workflow Dependencies

```
Auto-Fix Code Quality
    ↓
Auto-commit (main) OR PR Comment (PR)

Dependency Updates
    ↓
Auto-create PR
    ↓
Telegram Notification

Run Bot
    ↓
Self-dispatch next run (~15 min before window ends)
    ↓
Cron fallback restarts if the chain breaks
```

---

## Secrets Required

Configure these in GitHub repository settings → Secrets:

| Secret | Purpose | Required |
|--------|---------|----------|
| `BOT_TOKEN` | Telegram bot token (bot runtime + notifications) | Yes |
| `MONGODB_URI` | MongoDB connection string for the bot runtime | Yes |
| `OWNER_ID` | Your Telegram user ID (initial owner + notifications) | Yes |
| `BOT_PAT` | Personal Access Token with `workflow` scope, used by Run Bot to self-chain into the next run for seamless 24/7 coverage | Optional (recommended) |
| `GITHUB_TOKEN` | Auto-provided by GitHub Actions | Auto |

Without `BOT_PAT`, the Run Bot workflow cannot dispatch its own next run; it falls back to the every-30-minute cron resurrection schedule.

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

1. **Let auto-fix handle style** - Don't manually format, the workflow will do it
2. **Review dependency PRs weekly** - Auto-created PRs are safe to merge
3. **Read Telegram notifications** - Get instant feedback

### For Maintainers

1. **Monitor GitHub issues** - Auto-created issues need triage
2. **Review auto-fix commits** - Verify changes are correct
3. **Keep `BOT_PAT` valid** - An expired token breaks Run Bot self-chaining; the cron fallback still resurrects the bot, but with brief gaps
4. **Check workflow runs** - Weekly scheduled runs keep dependencies fresh

---

## Troubleshooting

### Telegram notifications not working
- Verify `BOT_TOKEN` and `OWNER_ID` secrets are set
- Verify bot can send messages to your user ID

### Auto-fix not committing
- Check branch protection rules allow bot commits
- Verify workflow has `contents: write` permission

### Dependency PR not created
- Verify `pull-requests: write` permission

### Bot not staying online (Run Bot)
- Verify `BOT_TOKEN`, `MONGODB_URI`, and `OWNER_ID` secrets are set
- For seamless 24/7, set `BOT_PAT` (a PAT with the `workflow` scope) so the run can dispatch its successor; otherwise only the 30-minute cron fallback restarts it
- A `409 Conflict` from Telegram means two instances are polling at once; the `tcf-bot-runner` concurrency group should prevent this, so check for a stray manual run

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

## Future Improvements

Potential additions:
- Docker image builds and pushes
- Deployment automation
- Security scanning with additional tools
