---
name: tcbot-feature-reviewer
description: Review TCF Bot feature changes for correctness, security, tests, documentation, Telegram UX, database impact, and project convention compliance.
---
Last updated: 2026-05-28


# TCBot Feature Reviewer

Use this skill when the user asks for a code review, final check, regression review, or "is this ready?" review of TCF Bot changes.

## Review Goals

Look for issues that matter in production:

- incorrect Telegram handler behavior,
- broken ConversationHandler states,
- unsafe callback query handling,
- missing permission or role checks,
- raw database calls from modules,
- unescaped HTML/user input,
- unbounded multi-group API fan-out,
- secrets or private IDs accidentally committed,
- missing tests for changed behavior,
- stale docs after behavior changes.

Keep feedback practical. Prioritize actionable issues over style preferences.

## Review Scope Checklist

### Telegram Handlers

- Command handlers are in `tcbot/modules/`.
- Shared workflows are in `tcbot/modules/helper/workflows/*_flow.py`.
- CallbackQuery handlers call `await q.answer()` before follow-up actions.
- Bot responses use `parse_mode="HTML"` when formatting is present.
- User-controlled text is escaped with formatter helpers.
- Long-running or multi-chat operations handle exceptions.

### Roles and Permissions

- Role checks use canonical helpers from `tcbot.database.roles_db`.
- Executor/target comparisons use role hierarchy helpers.
- Ban/kick flows auto-demote federation role holders before enforcement.
- Founder/admin/developer/tester protections are preserved.

### Database Impact

- Module code uses `tcbot.database.*_db` helpers instead of direct collection access.
- New fields are backward-compatible or documented with migration notes.
- New collections include indexes in `mongos.ensure_indexes()`.
- Query shapes match available indexes when performance matters.

### Async Behavior

- Fan-out across groups uses `tcbot.utils.dispatch.fan_out()`.
- Parallel `asyncio.gather()` calls are safe and do not hide required ordering.
- Background tasks do not leave conversations in confusing states.
- Tests use `AsyncMock` and offline fakes instead of real Telegram/MongoDB.

### Documentation and Tests

- Behavior changes update related docs in `docs/`, `README.md`, or `agents/` when appropriate.
- New database helpers, formatters, decorators, workflows, or critical branches have tests.
- Test commands use `uv run --extra test pytest ...` when pytest extras are needed.

## Review Workflow

1. Check `git status` and identify changed files.
2. Inspect diffs before reading full files.
3. Read surrounding code for each risky change.
4. Run targeted validation if possible.
5. Escalate to broader validation only when needed.
6. Report findings by severity.

Suggested commands:

```bash
git --no-pager diff --stat
git --no-pager diff --check
uv run ruff check .
uv run --extra test pytest tests/ -q
```

## Finding Format

Use this format for review findings:

```text
Severity: High | Medium | Low
File: path/to/file.py:line
Issue: What is wrong or risky.
Impact: What can break for users/operators.
Fix: Concrete suggested change.
```

If there are no blocking findings, say so clearly and mention what validation was run.

## Avoid

- Do not request broad rewrites for small issues.
- Do not nitpick formatting if Ruff handles it.
- Do not suggest direct MongoDB calls from modules.
- Do not expose secrets from config files or logs.
- Do not silently fix unrelated issues unless the user asked for an implementation pass.
