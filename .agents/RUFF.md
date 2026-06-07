# Ruff and Validation: TCF Bot

Read [`CLAUDE.md`](CLAUDE.md) first. This file defines validation commands and quality checks for the project. For code style enforced by Ruff, see [`STYLE-CODE.md`](STYLE-CODE.md). For development workflow, see [`WORKFLOW.md`](WORKFLOW.md). For CI/CD that runs these commands automatically, see [`../docs/workflows-guide.md`](../docs/workflows-guide.md).

---

## Tooling

- Dependency manager: `uv`.
- Formatter/linter: Ruff.
- Python target: 3.12.

Install runtime dependencies:

```bash
uv sync
```

---

## Ruff Commands

Format all files:

```bash
uv run ruff format .
```

Lint and apply safe fixes:

```bash
uv run ruff check --fix .
```

Check without modifying files:

```bash
uv run ruff check .
```

Ruff settings live in `pyproject.toml`. Keep source compatible with that file
rather than relying on editor-specific settings.

---

## Recommended Validation by Change Type

| Change type | Minimum validation |
|---|---|
| Documentation-only | Read changed docs; optionally run Markdown preview or spell check |
| Formatter/comment-only code change | `uv run ruff format .` and `uv run ruff check .` |
| Command handler change | `uv run ruff check --fix .`, then start the bot to confirm clean startup |
| Database helper change | `uv run ruff check --fix .` and an import check of the changed module |
| Workflow change | `uv run ruff check --fix .` and an import check of the changed flow |
| Dependency/config change | `uv sync`, then `uv run ruff format .` and `uv run ruff check .` |

Do not claim validation passed unless the command ran and exited successfully.
If validation cannot run, report the exact command and error.

---

## Common Failure Handling

1. Read the first Ruff error carefully; fix the root cause, not the symptom.
2. If a failure is caused by your change, fix it before finalizing.
3. If a pre-existing unrelated failure appears, report it clearly with the
   command output and continue only if the task can still be completed safely.
4. Do not weaken or disable lint rules to silence a warning unless the change is
   intentional and documented.

---

## Final Reporting

When finishing a task, include:

- Files changed.
- Validation commands run.
- Whether each command passed, failed, or could not run.
- Any remaining known issues or follow-up recommendations.
