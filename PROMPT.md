# TCF Bot Engineering Prompt

## Mission

Maintain and improve TCF Bot as a production Telegram federation bot. Work
autonomously through the requested scope, inspect the real implementation
before making claims, preserve existing behavior unless the task requires a
change, and stop only after the requested work is verified.

## Autonomous Engineering Loop

For every requested improvement, update, fix, or audit, run this bounded loop
without waiting for another prompt:

1. **Scope**: translate the request into one focused concern and identify the
   affected runtime, documentation, configuration, and validation surfaces.
2. **Inspect**: read the canonical rules, search for existing helpers and
   duplicate paths, inspect the current implementation, and check repository
   status before editing.
3. **Verify**: confirm external library APIs and version-sensitive behavior with
   Context7 latest. Resolve the library first, query one concept at a time,
   never include secrets, and stop after the documented call budget.
4. **Design**: choose the smallest modular change. Reuse and centralize shared
   behavior in the owning helper or domain module instead of adding parallel
   abstractions.
5. **Implement**: make the focused change with current Python, typed async
   code, accurate comments, and no speculative fallback or placeholder.
6. **Validate**: run targeted checks first, then the project verification suite,
   inspect logs for runtime changes, and scan for stale paths, dead code, and
   duplicated logic.
7. **Review**: compare the result with every explicit requirement, update
   related documentation and changelog entries, and repeat the loop only when a
   concrete issue remains. Stop when checks are clean or report the exact
   blocker after the bounded attempts.

Avoid unsupported latency guarantees. Prefer measurable improvements, bounded
concurrency, and clear failure behavior over unsafe shortcuts.

## Canonical project references

Read the following before changing the project:

1. `.agents/rules/tooling-validation.md`
2. `.agents/rules/code-style.md`
3. `.agents/rules/comment-style.md`
4. `AGENTS.md`
5. `CHANGELOG.md`
6. The relevant skill in `.agents/skills/`
7. The relevant source and documentation files

The three files under `.agents/rules/` are the canonical sources for engineering
constraints. Do not invent a second project-state tracker or duplicate project
rules elsewhere.

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

- Use Python 3.14 syntax, `uv`, and Ruff and Pyright.
- Follow the module boundaries and handler conventions in `AGENTS.md`.
- Use database helpers instead of direct collection access from handlers.
- Bound cross-group Telegram fan-out with the shared dispatch helper.
- Escape user-controlled text and keep bot messages in HTML parse mode.
- Preserve role checks, anonymous-admin handling, callback acknowledgement,
  async task error handling, and explicit PTB lifecycle management.
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
