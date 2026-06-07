# GitHub Workflows Documentation

This document describes all GitHub Actions workflows configured for the TCF Bot project.

For user-facing overview of CI/CD, see [`../README.md`](../README.md#cicd--automation). For contributor commit and PR guidance, see [`../AGENTS.md`](../AGENTS.md#commit-and-pull-request-guidance). For changelog of CI/CD additions, see [`../CHANGELOG.md`](../CHANGELOG.md).

## Overview

The project uses 5 automated workflows for continuous integration, code quality, and maintenance:

1. **Auto-Fix Code Quality** - Automatically fix linting issues
2. **Dependency Updates** - Weekly dependency updates with auto-PR
3. **Performance Regression Detection** - Track performance metrics
4. **CodeQL** - Security analysis
5. **Run Bot** - Scheduled 24/7 runner (hourly, 55-minute window)

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
## 🤖 Automated Dependency Update

This PR updates project dependencies to their latest compatible versions.

### Changes
- python-telegram-bot: <old> → <new>
- motor: <old> → <new>

Safe to merge with new versions.
```

---

## 3. Performance Regression Detection

**File:** `.github/workflows/performance.yml`

**Triggers:**
- Push to `main`
- Pull requests to `main`
- Manual dispatch

**What it does:**
- Runs performance benchmarks:
  - Batch query performance (100 users)
  - Mention data fetch (50 users)
  - Per-user operation time
- Compares with baseline from `main` branch
- Detects regressions (>10% slower)
- Detects improvements (>10% faster)
- **Comments on PR** with performance comparison
- **Creates issue** if regression detected on `main`
- **Auto-updates baseline** on `main` branch

**Benchmark Metrics:**
- `batch_query_100_users_ms` - Time to fetch 100 user names
- `batch_query_per_user_ms` - Average time per user
- `mention_data_50_users_ms` - Time to fetch mention data for 50 users
- `mention_data_per_user_ms` - Average time per user

**Example PR Comment:**
```
## 📊 Performance Benchmark Results

## ✅ Performance Improvements

- batch_query_100_users_ms: 45.23ms → 28.15ms (-37.8%)
- mention_data_50_users_ms: 23.45ms → 18.92ms (-19.3%)

## ✅ No significant performance changes

All other metrics within ±10% of baseline.
```

---

## 4. CodeQL

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

## 5. Run Bot

**File:** `.github/workflows/run-bot.yml`

**Triggers:**
- Scheduled every hour (`0 */1 * * *`)
- Manual dispatch

**What it does:**
- Runs the bot for a 55-minute window per execution (5 × ~55 min overlaps for continuous coverage)
- Pulls latest changes before each run to stay current
- Detects crashes by scanning `bot.log` for `Traceback`, `Error:`, or `CRITICAL`
- Uploads bot log and crash tail as artifacts (7-day retention) for post-mortem analysis

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

Performance Regression
    ↓
Compare with baseline
    ↓
PR Comment OR Issue (regression)
```

---

## Secrets Required

Configure these in GitHub repository settings → Secrets:

| Secret | Purpose | Required |
|--------|---------|----------|
| `BOT_TOKEN` | Telegram bot token for notifications | Yes |
| `OWNER_ID` | Your Telegram user ID for notifications | Yes |
| `GITHUB_TOKEN` | Auto-provided by GitHub Actions | Auto |

---

## Notification Examples

### Dependency Update
```
🔄 Dependency Update - ✅ PASS

Dependencies updated
Result: PR created

View workflow
```

---

## Best Practices

### For Developers

1. **Let auto-fix handle style** - Don't manually format, the workflow will do it
2. **Review dependency PRs weekly** - Auto-created PRs are safe to merge
3. **Watch for performance regressions** - Check PR comments for benchmark results
4. **Read Telegram notifications** - Get instant feedback

### For Maintainers

1. **Monitor GitHub issues** - Auto-created issues need triage
2. **Review auto-fix commits** - Verify changes are correct
3. **Update baselines** - Performance baselines auto-update on `main`
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

### Performance benchmarks failing
- Ensure MongoDB is available
- Check benchmark script for errors
- Verify baseline file exists on `main` branch

---

## Maintenance

### Weekly Tasks (Automated)
- ✅ Dependency updates (Monday 04:00 UTC)
- ✅ Code quality fixes (Monday 04:00 UTC)

### Manual Tasks
- Review and merge dependency update PRs
- Triage auto-created issues
- Monitor performance regression issues

---

## Future Improvements

Potential additions:
- Docker image builds and pushes
- Deployment automation
- Security scanning with additional tools
