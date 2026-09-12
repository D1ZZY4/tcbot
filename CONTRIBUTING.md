# Contributing to TCF Bot

Thank you for helping improve TCF Bot. Every contribution, from a typo fix
to a new moderation flow, makes the federation safer for thousands of
members. This guide walks you through the whole process: setup, branches,
validation, and pull requests.

> [!NOTE]
> This guide is written for **human contributors**. It assumes you, not an
> assistant, are reading it.
>
> - If you work with AI coding assistants on this repository, **you** are
>   responsible for pointing them at the agent contract first:
>   [`AGENTS.md`](AGENTS.md) (or [`CLAUDE.md`](CLAUDE.md)), [`PROMPT.md`](PROMPT.md),
>   and the rules under [`.agents/rules/`](.agents/rules/). Do not let an
>   assistant touch code until it has completed that reading checkpoint.
> - If you **are** an AI agent reading this file, treat it as orientation
>   only. Your working contract is [`AGENTS.md`](AGENTS.md) (or
>   [`CLAUDE.md`](CLAUDE.md)) plus [`PROMPT.md`](PROMPT.md): complete that
>   reading checkpoint, learn what this project is, and only then change
>   any code.

## Understand the Project First

If you are here to maintain this bot or contribute to it, read the
documented project before touching code. [`docs/README.md`](docs/README.md)
is the documentation index and maps the complete, maintained picture.

Suggested reading path:

1. [`README.md`](README.md) for the project overview and setup.
2. [`docs/README.md`](docs/README.md) as the index, then the
   [repository map](docs/architecture/repository-map.md) for structure,
   ownership, and startup flow.
3. The [workflow overview](docs/features/workflow-overview.md) plus the
   feature guide for the area you plan to change (moderation, roles,
   appeals, or statistics).
4. [`CHANGELOG.md`](CHANGELOG.md) for what changed recently and why.

The index also covers operations (backup, CI/CD, performance, Vercel)
and stable references (keyboard styles). Reading it first is faster
than reverse-engineering the codebase.

## Ways to Contribute

- **Code**: bug fixes and focused improvements (see [Development
  Workflow](#development-workflow)). For large or architectural changes,
  open an issue first so maintainers can agree on the direction before
  you write code.
- **Documentation**: setup guides, feature docs, and examples. Docs-only
  contributions are welcome and follow a lighter validation path (see
  [Validation](#validation)).
- **Bug reports**: describe what happened, what you expected, the bot
  version or commit, and reproduction steps using placeholder IDs only.
  Never paste tokens, credentials, or private chat IDs; see
  [Security](#security) and [`SECURITY.md`](SECURITY.md).

## Ground Rules

- **Do not break backward compatibility.** Database schemas, callback-data
  formats, command names, and config keys must keep working unless a
  migration plan ships with the change.
- **Treat moderation code as critical infrastructure.** Ban, unban, mute,
  kick, warn, role, and authorization changes can affect every connected
  group. Verify success and failure paths, alternate entry points, and
  state transitions; never dismiss a moderation bypass as an edge case.
- **Never commit secrets.** No `config.env`, tokens, passwords, database
  URIs, webhook secrets, or private chat IDs. Not in code, not in logs,
  not in screenshots.
- **Keep bot messages English-only** and in MarkdownV2 parse mode (never
  HTML), with user-provided text escaped.

> [!CAUTION]
> A small bug in moderation logic can affect thousands of users across
> dozens of groups. When in doubt, ask a maintainer before merging.

## Local Setup

Requirements:

- Python 3.14
- `uv`
- MongoDB for runtime work (Atlas or self-hosted)
- Redis only when testing the optional L2 cache

Fork the repository, then clone your fork:

```bash
git clone https://github.com/<your-username>/tcbot
cd tcbot
```

Install the locked dependencies and prepare a local-only config:

```bash
uv sync --frozen
cp config.env.example config.env
```

Fill `config.env` with placeholders or local values only, then run the bot:

```bash
uv run python -m tcbot
```

> [!IMPORTANT]
> `config.env` is yours alone. It must never be committed.

## Development Workflow

1. Sync with `main` and create a focused branch. Use lowercase,
   hyphen-separated names describing the change (for example,
   `fix-warn-expiry` or `help-docs`), branched off `main`.
2. Choose one focused concern per change. Inspect the current
   implementation before editing.
3. Respect module boundaries:

   | Concern | Location |
   |---|---|
   | Command handlers | `tcbot/modules/` |
   | Conversation flows (`*_flow.py`) | `tcbot/modules/helper/workflows/` |
   | Shared handler helpers | `tcbot/modules/helper/` |
   | MongoDB access (always via helpers, never raw) | `tcbot/database/` |
   | Runtime utilities | `tcbot/utils/` |

4. Reuse the existing workflow, role, formatting, and dispatch helpers
   instead of duplicating behavior.
5. Update documentation and diagrams when behavior or structure changes,
   and add a concise entry under `[Unreleased]` in [`CHANGELOG.md`](CHANGELOG.md).
6. Do not bump versions; maintainers cut releases separately.

## Commits

Use a scoped Conventional Commit, such as `feat(moderation): add ...`,
`fix(cache): correct ...`, or `docs(contributing): explain ...`. Keep
one logical change per commit with a useful body for non-trivial
changes, and give every commit its own `CHANGELOG.md` slice.

## Validation

Run the checks relevant to the change. For most code changes:

```bash
uv run ruff format --check .
uv run ruff check .
uv run --with pyright pyright .
uv run python -m compileall -q tcbot
uv run python -c "import tcbot"
git diff --check
```

When your change touches behavior and the test suite is available, also run:

```bash
uv run --with pytest python -m pytest tests/ -q
```

For documentation-only changes, at minimum read the changed files, check
relative links and stale paths, and run:

```bash
git diff --check
```

If a validation command cannot run, include the exact command and error in the
pull request description.

> [!TIP]
> CI runs these same checks and fails the pull request on violations. Run them locally before pushing.

## Pull Requests

1. Push your branch to your fork and open a pull request against `main`.
2. Explain what changed and why, which user, operator, or contributor
   behavior is affected, and any configuration, database, migration, or
   deployment impact.
3. List the validation commands you ran and their results.
4. Attach screenshots or log excerpts only when they clarify a
   user-visible change.
5. Respond to review comments (a short "Done" or the reason you did not
   apply a suggestion), keep the branch updated with `main`, and avoid
   rewriting history once review has started.

## Review Checklist

- [ ] The change is limited to the intended scope.
- [ ] Existing behavior and backward compatibility are preserved unless the
      change intentionally modifies them.
- [ ] Documentation and `CHANGELOG.md` are updated where needed.
- [ ] No secrets or private deployment data are included.
- [ ] Relevant validation commands pass.
- [ ] The pull request explains configuration, database, or deployment impact.

## Security

Do not report security-sensitive details in a public issue. Follow
[`SECURITY.md`](SECURITY.md): describe the impact and reproduction safely,
then contact a maintainer privately.
