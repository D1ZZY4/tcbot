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

Current active ruleset (from `pyproject.toml`):

```
select = ["B", "C4", "D", "E4", "E7", "E9", "F", "FBT", "I", "PERF", "PIE", "PLC", "PLE", "PTH", "RET", "RUF", "SIM", "TC", "TRY400", "TRY401", "UP", "W"]
ignore  = [
    "D203",    # Conflicts with D211 (no-blank-line-before-class); D211 is preferred
    "D213",    # Conflicts with D212 (multi-line-summary-first-line); D212 is preferred
    "RUF001",  # Ambiguous unicode: › intentionally used as breadcrumb separator in bot UI text
    "TC001",   # Application imports in TYPE_CHECKING: internal TypedDicts used in runtime dict ops
    "UP047",   # Generic functions: TypeVar-based style kept for ratelimiter compatibility
]
exclude = [".local/", ".agents/", ".kilo/", ".trae/", ".claude/", "attached_assets/"]
```

Rules intentionally not added:
- `PLR` (Pylint-refactoring): `PLR0912` (too-many-branches) and `PLR0915` (too-many-statements) fire on large flow functions that are already logically decomposed; too noisy for conversation-heavy handlers.
- `T20` (flake8-print): `__main__._print_fatal` uses `print(..., file=sys.stderr)` intentionally.
- `ANN` (annotations): `ANN401` fires on legitimate `Any` in generic cache/date helpers; too noisy to enable globally.
- `TRY` (full suite): `TRY003` (long exception messages) and `TRY300` (else-after-try) are pedantic; only `TRY400` and `TRY401` are selected.
- `ARG` (unused arguments): PTB handlers must accept `(update, ctx)` regardless of whether `ctx` is used; 43+ intentional unused `ctx` args.
- `EM` (error message strings): `EM102` (f-string in exceptions) is pedantic for `SystemExit` cases; exceptions are non-critical `SystemExit`, not raised exception classes.
- `S104` (bind to all interfaces): `alive.py` binds to `0.0.0.0` intentionally for the Flask keep-alive server required by Replit.
- `FBT002` (boolean default positional): already covered by making params keyword-only (FBT001); no separate default-value violations remain.

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
