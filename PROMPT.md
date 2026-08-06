# TCF Bot Engineering Prompt

## Mission

Maintain and improve TCF Bot as a production Telegram federation bot. Work
autonomously through the requested scope, inspect the real implementation
before making claims, preserve existing behavior unless the task requires a
change, and stop only after the requested work is verified.

## Canonical project references

Read the following before changing the project:

1. `.agents/rules/RULES.md`
2. `AGENTS.md`
3. `CHANGELOG.md`
4. The relevant skill in `.agents/skills/`
5. The relevant source and documentation files

The rules file is the canonical source for engineering constraints. Do not
invent a second project-state tracker or duplicate project rules elsewhere.

## Technical priorities

- Preserve federation moderation safety, role hierarchy, and database
  compatibility.
- Keep production transport webhook-first. Polling is only the local
  development fallback when no public URL is available.
- Keep `WEBHOOK_SECRET` optional. Runtime generation is valid when it is not
  configured.
- Treat scheduler readiness as valid only after schedules are registered and
  background execution has started. Propagate startup failures.
- Return HTTP `503` when a webhook update cannot be enqueued so Telegram can
  retry it.
- Preserve FIFO ordering for Redis mutations sharing a prefix and event loop.
- Keep the Redis `v2` namespace and typed JSON serialization compatible with
  existing untagged values.
- Use `clear_all()` for prefix-wide cache invalidation and `clear()` only for
  L1 invalidation.
- Do not add dependencies unless the task explicitly requires one.
- Keep the accepted APScheduler security risk documented and do not blindly
  upgrade or downgrade the pinned version.

## Implementation standards

- Use Python 3.12 syntax, `uv`, and Ruff.
- Follow the module boundaries and handler conventions in `AGENTS.md`.
- Use database helpers instead of direct collection access from handlers.
- Bound cross-group Telegram fan-out with the shared dispatch helper.
- Escape user-controlled text and keep bot messages in HTML parse mode.
- Preserve role checks, anonymous-admin handling, callback acknowledgement,
  async task error handling, and explicit PTB lifecycle management.
- Use Context7 through `.agents/skills/context7-expert/` for current library
  APIs, or inspect the installed source when Context7 is unavailable.
- Do not log secrets, tokens, credentials, raw private input, or private chat
  identifiers.
- Do not leave dead links, stale behavior descriptions, or placeholder fixes.

## Documentation and cleanup

When behavior or structure changes:

- Update `CHANGELOG.md` under `[Unreleased]`.
- Update affected files in `docs/`, `README.md`, `AGENTS.md`, `replit.md`, and
  `.agents/` as needed.
- Update Mermaid diagrams when their described flow or structure changes.
- Sweep the repository for stale paths, broken links, and obsolete instructions.
- Keep project documentation in professional English. Agent responses may use
  the user's language.

## Verification

Run the checks relevant to the change. For runtime or dependency changes,
include:

```bash
uv sync --frozen
uv run ruff format --check .
uv run ruff check .
uv run python -m compileall -q tcbot
uv run python -c "import tcbot"
git diff --check
```

For runtime changes, restart the configured `Start Application` workflow and
inspect its logs. Confirm that startup reaches the expected readiness state.
For documentation-only changes, run the stale-reference scan, JSON validation
for changed JSON files, and `git diff --check`.

## Commit policy

- Make one focused Conventional Commit for the completed logical change.
- Read `docs/git-commit.md` before committing.
- Use author `D1ZZY4 <176969112+D1ZZY4@users.noreply.github.com>`.
- Include the required `Author-by` and `Signed-off-by` trailers.
- Never push unless the user explicitly asks.
- Review the final diff and status before committing.