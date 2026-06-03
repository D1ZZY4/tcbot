# GitHub Workflows Documentation

This document describes all GitHub Actions workflows configured for the TCF Bot project.

For user-facing overview of CI/CD, see [`../README.md`](../README.md#cicd--automation). For contributor commit and PR guidance, see [`../AGENTS.md`](../AGENTS.md#commit-and-pull-request-guidance). For changelog of CI/CD additions, see [`../CHANGELOG.md`](../CHANGELOG.md).

## Overview

The project uses 7 automated workflows for continuous integration, code quality, and maintenance:

1. **TDD - Multi-Python Matrix** - Test suite across Python versions
2. **TDD - Verification Report** - Aggregate test results and notify
3. **Auto-Fix Code Quality** - Automatically fix linting issues
4. **Dependency Updates** - Weekly dependency updates with auto-PR
5. **Performance Regression Detection** - Track performance metrics
6. **CodeQL** - Security analysis
7. **Run Bot** - Scheduled 24/7 runner (hourly, 55-minute window)

---

## 1. TDD - Multi-Python Matrix

**File:** `.github/workflows/run-tdd.yml`

**Triggers:**
- Push to `main`, `feat/**`, `fix/**`, `refactor/**`
- Pull requests to `main`
- Weekly schedule (Monday 03:00 UTC)
- Manual dispatch

**What it does:**
- Runs pytest across Python 3.12 and 3.13
- Uses locked dependencies (`uv.lock --frozen`) for reproducibility
- Generates JUnit XML reports
- Uploads test artifacts for verification workflow

**Configuration:**
- Timeout: 20 minutes
- Fail-fast: disabled (all versions run even if one fails)
- Artifacts retained: 14 days

---

## 2. TDD - Verification Report

**File:** `.github/workflows/verification.yml`

**Triggers:**
- After TDD workflow completes
- Manual dispatch

**What it does:**
- Downloads test artifacts from TDD workflow
- Parses JUnit XML results
- Creates detailed GitHub summary with:
  - Pass/fail/skip counts per Python version
  - Top 50 failing tests with reasons
  - Diagnostic recommendations
- **Auto-creates GitHub issue** on test failures
- **Sends enhanced Telegram notification** with:
  - ✅/❌ Status with emoji
  - Commit SHA and branch name
  - Detailed pass/fail/skip counts
  - Top 3 failing tests (if any)
  - Link to full report

**Notification Format:**
```
TCF Bot TDD - ✅ PASS

Commit: 7c6ae2c
Branch: main

Results:
  ✅ Passed: 605
  ❌ Failed: 0
  ⏭ Skipped: 12

View full report
```

**On Failure:**
```
TCF Bot TDD - ❌ FAIL

Commit: 7c6ae2c
Branch: feat/new-feature

Results:
  ✅ Passed: 246
  ❌ Failed: 4
  ⏭ Skipped: 0

Top failures:
- `test_ban_flow.test_proof_upload` - FAIL: AssertionError
- `test_stats.test_user_list` - ERROR: KeyError: 'username'
- `test_check.test_warns_in_group` - FAIL: Expected 3, got 2
...and 1 more

View full report
```

---

## 3. Auto-Fix Code Quality

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

## 4. Dependency Updates

**File:** `.github/workflows/dependency-update.yml`

**Triggers:**
- Weekly schedule (Monday 04:00 UTC)
- Manual dispatch

**What it does:**
- Runs `uv lock --upgrade` to update all dependencies
- Installs updated dependencies
- **Runs full test suite** with new versions
- If tests pass:
  - **Auto-creates PR** with dependency updates
  - PR includes diff of changes and test results
- If tests fail:
  - **Auto-creates issue** with failure details
  - Includes test log for debugging
- **Sends Telegram notification** with result

**Benefits:**
- Always up-to-date dependencies
- Automated testing before merge
- Zero manual work for routine updates
- Immediate notification of breaking changes

**Example PR:**
```
Title: chore: Auto-update dependencies

Body:
## 🤖 Automated Dependency Update

This PR updates project dependencies to their latest compatible versions.

### Test Results
✅ All tests passing with updated dependencies

### Changes
- python-telegram-bot: 22.5 → 22.6
- motor: 3.7.1 → 3.8.0
- pytest: 9.0.3 → 9.1.0

Safe to merge - all tests pass with new versions.
```

---

## 5. Performance Regression Detection

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

## 6. CodeQL

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

## 7. Run Bot

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
TDD Multi-Python Matrix
    ↓
TDD Verification Report
    ↓
Telegram Notification + GitHub Issue (on failure)

Auto-Fix Code Quality
    ↓
Auto-commit (main) OR PR Comment (PR)

Dependency Updates
    ↓
Test with new deps
    ↓
Auto-create PR (pass) OR Issue (fail)
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

### Test Pass
```
TCF Bot TDD - ✅ PASS

Commit: 04def72
Branch: main

Results:
  ✅ Passed: 605
  ❌ Failed: 0
  ⏭ Skipped: 0

View full report
```

### Test Fail with Details
```
TCF Bot TDD - ❌ FAIL

Commit: 7c6ae2c
Branch: feat/new-stats

Results:
  ✅ Passed: 246
  ❌ Failed: 4
  ⏭ Skipped: 2

Top failures:
- `test_stats.test_batch_query` - FAIL: AssertionError: Expected dict, got None
- `test_check.test_warns_list` - ERROR: KeyError: 'username'
- `test_ban.test_proof_upload` - FAIL: Mock not called
...and 1 more

View full report
```

### Dependency Update
```
🔄 Dependency Update - ✅ PASS

Dependencies updated and tested
Result: PR created

View workflow
```

---

## Best Practices

### For Developers

1. **Let auto-fix handle style** - Don't manually format, the workflow will do it
2. **Review dependency PRs weekly** - Auto-created PRs are safe to merge if tests pass
3. **Watch for performance regressions** - Check PR comments for benchmark results
4. **Read Telegram notifications** - Get instant feedback on test failures

### For Maintainers

1. **Monitor GitHub issues** - Auto-created issues need triage
2. **Review auto-fix commits** - Verify changes are correct
3. **Update baselines** - Performance baselines auto-update on `main`
4. **Check workflow runs** - Weekly scheduled runs keep dependencies fresh

---

## Troubleshooting

### Telegram notifications not working
- Verify `BOT_TOKEN` and `OWNER_ID` secrets are set
- Check bot token is not a test token
- Verify bot can send messages to your user ID

### Auto-fix not committing
- Check branch protection rules allow bot commits
- Verify workflow has `contents: write` permission

### Dependency PR not created
- Check if tests passed with new dependencies
- Look for auto-created issue if tests failed
- Verify `pull-requests: write` permission

### Performance benchmarks failing
- Ensure MongoDB is available (uses test connection)
- Check benchmark script for errors
- Verify baseline file exists on `main` branch

---

## Maintenance

### Weekly Tasks (Automated)
- ✅ Dependency updates (Monday 04:00 UTC)
- ✅ Code quality fixes (Monday 04:00 UTC)
- ✅ Locked dependency verification (Monday 03:00 UTC)

### Manual Tasks
- Review and merge dependency update PRs
- Triage auto-created issues
- Monitor performance regression issues

---

## Future Improvements

Potential additions:
- Coverage tracking and reporting
- Docker image builds and pushes
- Deployment automation
- Integration testing with real MongoDB
- Load testing workflows
- Security scanning with additional tools
