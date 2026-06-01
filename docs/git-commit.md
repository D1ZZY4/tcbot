# Git Commit Style

For contributor PR guidance, see [`../AGENTS.md`](../AGENTS.md). For automated CI/CD that runs on commits, see [`workflows-guide.md`](workflows-guide.md).

Use focused commits that describe one logical change.

## Subject line

- Use the imperative mood: `Add`, `Fix`, `Update`, `Refactor`.
- Capitalize the first word.
- Do not end with punctuation.
- Keep it short, ideally 50 characters or fewer.
- Prefer a body only when it adds useful context.
- MUST BE add:
  - Author-by: Dizzy <176969112+D1ZZY4@users.noreply.github.com>
  - Signed-off-by: Dizzy <176969112+D1ZZY4@users.noreply.github.com>

Good examples:

```text
Update developer docs
Fix appeal review lockout
Add warning counter backfill
Refactor module discovery docs

Author-by: Dizzy <176969112+D1ZZY4@users.noreply.github.com>
Signed-off-by: Dizzy <176969112+D1ZZY4@users.noreply.github.com>
```

Avoid:

```text
Updated files
fix bug.
WIP
Changes from today
```

## MUST BE USED PREFIXES

Author-by: Dizzy <176969112+D1ZZY4@users.noreply.github.com>
Signed-off-by: Dizzy <176969112+D1ZZY4@users.noreply.github.com>

Project commit guidance allows conventional prefixes when useful:

| Prefix | Use for |
|---|---|
| `feat:` | User-facing feature additions. |
| `fix:` | Bug fixes. |
| `refactor:` | Behavior-preserving code restructuring. |
| `docs:` | Documentation-only changes. |
| `test:` | Test-only changes. |
| `chore:` | Maintenance and tooling changes. |

Examples:

```text
docs: Update setup and architecture docs, see `CHANGELOG.md` for more details.
fix: Handle missing appeal review timestamp, see `CHANGELOG.md` for more details.
refactor: Centralize warn counter updates, see `CHANGELOG.md` for more details.


```

## Body format

Use a body when the subject cannot explain the why or impact.

```text
Fix appeal review lockout

Normalize stored review timestamps before comparing them with the
12-hour reviewer priority window. (see `CHANGELOG.md` for more details)
```

Rules:

- Separate subject and body with a blank line.
- Wrap body lines around 72 characters.
- Explain why, risk, or migration impact; do not repeat the subject.
- Explain long or short descriptions for complex changes on `CHANGELOG.md`.

## Before committing

For code changes, run targeted validation first, then broader checks when practical:

```bash
uv run --extra test pytest tests/ -v
uv run ruff format .
uv run ruff check --fix .
```

For documentation-only changes, a docs review or test collection check is usually enough:

```bash
uv run --extra test pytest --collect-only -q
```

Never include secrets, real tokens, MongoDB URIs, private passwords, or private chat IDs in commits.
