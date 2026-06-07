# Git Commit Style

For contributor PR guidance, see [`../AGENTS.md`](../AGENTS.md).
For automated CI/CD that runs on commits, see [`workflows-guide.md`](workflows-guide.md).

Use focused commits: one logical change per commit, no unrelated changes bundled together.

---

## Subject Line

- Use the imperative mood: `Add`, `Fix`, `Update`, `Refactor`, `Remove`.
- Capitalize the first word.
- Do not end with punctuation.
- Keep it 50 characters or fewer.
- Write it so the sentence "If applied, this commit will..." reads naturally.

Good examples:

```text
Update developer docs
Fix appeal review lockout
Add warning counter backfill
Refactor module discovery logic
Remove deprecated broadcast helper
```

Avoid:

```text
Updated files
fix bug.
WIP
Changes from today
misc fixes
```

---

## Conventional Prefixes

Use a prefix when it adds clarity about the change type. Prefix goes before
the subject, lowercase, followed by a colon and a space.

| Prefix | Use for |
|---|---|
| `feat:` | User-facing feature additions |
| `fix:` | Bug fixes |
| `refactor:` | Behavior-preserving code restructuring |
| `docs:` | Documentation-only changes |
| `chore:` | Maintenance, tooling, dependency updates |
| `perf:` | Performance improvements with no behavior change |
| `security:` | Security fixes or hardening |
| `style:` | Formatting, whitespace, lint fixes only |

You may add a scope in parentheses to narrow context:

```text
feat(ban): Add auto-demote on ban for federation role holders
fix(appeal): Handle missing review timestamp
refactor(database): Extract all mongo queries from handlers
docs(architecture): Update Mermaid diagrams to reflect new structure
chore(deps): Bump python-telegram-bot to latest
security(auth): Enforce resolve_and_check on unguarded handler
perf(fan-out): Replace sequential broadcast loop with bounded gather
```

For documentation-only or maintenance commits, the prefix alone without a
scope is fine:

```text
docs: Update setup and architecture docs
fix: Handle missing appeal review timestamp
refactor: Centralize warn counter updates
chore: Clean up unused imports across modules
```

---

## Body

Use a body when the subject line cannot explain the why, the risk, or the
migration impact.

```text
Fix appeal review lockout

Normalize stored review timestamps before comparing them with the
12-hour reviewer priority window. Without this, reviewers who had
pending appeals were permanently locked out after a bot restart.

See CHANGELOG.md for full details.
```

Rules:

- Separate subject and body with a blank line.
- Wrap body lines at 72 characters.
- Explain why, not what (the diff shows what).
- Note risk, migration impact, or breaking changes when relevant.
- Reference CHANGELOG.md for longer context; do not duplicate it here.

---

## Required Trailers

Every commit MUST include these two trailers at the end, after a blank line
following the body (or after the subject if there is no body):

```text
Author-by: Dizzy <176969112+D1ZZY4@users.noreply.github.com>
Signed-off-by: Dizzy <176969112+D1ZZY4@users.noreply.github.com>
```

Full commit example with body and trailers:

```text
Fix appeal review lockout

Normalize stored review timestamps before comparing them with the
12-hour reviewer priority window. Without this, reviewers with
pending appeals were locked out after a bot restart.

See CHANGELOG.md for full details.

Author-by: Dizzy <176969112+D1ZZY4@users.noreply.github.com>
Signed-off-by: Dizzy <176969112+D1ZZY4@users.noreply.github.com>
```

Short commit example (no body needed):

```text
Update developer docs

Author-by: Dizzy <176969112+D1ZZY4@users.noreply.github.com>
Signed-off-by: Dizzy <176969112+D1ZZY4@users.noreply.github.com>
```

---

## Before Committing

For code changes, run formatting and lint checks first:

```bash
uv run ruff format .
uv run ruff check --fix .
```

When the change touches `pyproject.toml`, module structure, or entry points,
also run:

```bash
uv sync
uv pip install -e .
uv run python -c "import tcbot; print('import OK')"
```

---

## What Never Goes in a Commit

- Secrets, real bot tokens, or MongoDB URIs.
- Private chat IDs or real user data.
- Hardcoded values that belong in `config.env`.
- Files matching `.gitignore` (check before `git add -A`).
- Unresolved merge conflict markers (`<<<<<<<`, `=======`, `>>>>>>>`).
- "TODO: fix later" comments in production code paths.