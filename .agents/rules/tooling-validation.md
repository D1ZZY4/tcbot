# Tooling and Validation Rules

This file defines the project workflow, dependency, documentation-maintenance,
and validation requirements for TCF Bot. Code conventions live in
[`code-style.md`](code-style.md), and comment and Markdown conventions live in
[`comment-style.md`](comment-style.md).

---

## Read Before Work and Update After Work

These rules apply to every task:

1. Before changing the repository, read this file, [`code-style.md`](code-style.md),
   [`comment-style.md`](comment-style.md), [`AGENTS.md`](../../AGENTS.md), and
   [`CHANGELOG.md`](../../CHANGELOG.md).
2. Read the relevant skill in [`.agents/skills/`](../skills/), source files,
   configuration, and documentation for the requested scope.
3. After a change, add an entry under `[Unreleased]` in
   [`CHANGELOG.md`](../../CHANGELOG.md).
4. Update related documentation, repository maps, skills, and guidance whose
   content or paths became stale.
5. Search for old paths and broken links before finalizing.

The three files in this directory are the canonical engineering rules. Public
contributor guidance belongs in [`CONTRIBUTING.md`](../../CONTRIBUTING.md);
deployment and feature documentation belongs under `docs/`.

## Skills and Sub-Agents

Skills in `.agents/skills/` apply automatically when their trigger matches.
Use the relevant skill before editing code, documentation, database helpers,
workflows, diagrams, or other specialized areas. Compose skills when a task
spans more than one area.

## Autonomous Improvement Loop

For each requested improvement, update, fix, or audit:

1. Scope one concern and identify its affected files and validation surfaces.
2. Inspect current code, existing helpers, repository status, and duplicate or
   dead paths before editing.
3. Verify version-sensitive library behavior with `npx ctx7@latest`: resolve
   the library first, query one concept at a time, and never send credentials
   or private project data.
4. Design and implement the smallest modular change using the owning helper or
   domain module as the single source of truth.
5. Run targeted checks, then the relevant full validation and runtime logs.
6. Review requirements, docs, stale paths, dead code, and duplicate logic.
7. Repeat only for a concrete remaining defect; stop after bounded attempts and
   report blockers precisely.

Performance claims require measurements. Prefer bounded concurrency and explicit
failure behavior.

## Dependency and Tooling Policy

- Target Python 3.12.
- Use `uv` for dependency installation, locking, and tool execution.
- Keep `pyproject.toml` and `uv.lock` synchronized.
- Do not add dependencies to `requirements.txt`.
- Do not change pinned dependencies blindly, especially the accepted
  APScheduler `4.0.0a6` integration risk.
- Keep runtime secrets in environment variables or the platform secret manager.
- Never edit or commit `config.env` during normal work.

Install dependencies from the lockfile:

```bash
uv sync --frozen
```

## Ruff and Validation

Format source files:

```bash
ruff format .
```

Apply safe lint fixes:

```bash
ruff check --fix .
```

Check without modifying files:

```bash
ruff format --check .
ruff check .
```

Replit note: if `ruff` is not on PATH, use `uv run ruff` instead. The
invocations above are the project's primary commands; the `uv run` prefix is
only a fallback for environments that resolve tools through the project venv.

Recommended minimum validation by change type:

| Change type | Minimum validation |
|---|---|
| Documentation-only | Read changed docs, scan links and stale paths, then run `git diff --check`. |
| Formatter or comment-only code change | `ruff format --check .` and `ruff check .` |
| Command handler change | Ruff checks, then start the bot and inspect startup logs. |
| Database helper change | Ruff checks and an import check of the changed module. |
| Workflow change | Ruff checks and an import check of the changed flow. |
| Dependency or configuration change | `uv sync --frozen`, Ruff checks, and an import check. |
| Runtime change | Ruff checks, compileall, import check, and a clean application startup. |

For the full runtime check:

```bash
ruff format --check .
ruff check .
uv run python -m compileall -q tcbot
uv run python -c "import tcbot"
git diff --check
```

Do not claim a validation command passed unless it actually ran and exited
successfully. If a check cannot run, report the exact command and error.

## Documentation Maintenance

- Keep Markdown in professional English.
- Describe implemented behavior, not unverified targets or guarantees.
- Keep public contributor and operator guidance separate from agent-only rules.
- Update `docs/README.md` when adding or reorganizing public documentation.
- Update `docs/architecture/repository-map.md` when the repository structure changes.
- Do not include credentials, private chat IDs, production-only links, or tokens.

## Security and Scope

- Preserve backward compatibility for production moderation, role, and database
  behavior.
- Do not log or document secrets, tokens, credentials, raw private input, or
  private chat identifiers.
- Do not edit unrelated files or refactor outside the requested scope.
- Do not remove meaningful behavior merely to silence a warning.
- Keep database schema changes backward-compatible unless a migration plan is
  included.

## Final Review

Before declaring work complete:

- Review the complete diff, including renames and deletions.
- Confirm all changed documentation links resolve.
- Confirm no ignored files or secrets are staged.
- Run the relevant validation commands.
- Leave the working tree clean after committing, when a commit was requested.