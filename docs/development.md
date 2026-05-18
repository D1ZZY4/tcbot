# Development Workflow and Onboarding - TCF Bot

This page describes development conventions, branch strategy, and test expectations.
Before contributing or changing repo behavior, review the `agents/` guidance so your work matches the project rules and environment expectations.
- `agents/RULES.md` - coding conventions, what is forbidden
- `agents/STYLE-CODE.md` - code style, typing, and formatting rules
- `agents/STYLE-COMMENTS.md` - comment and docstring style
- `agents/WORKFLOW.md` - branching, commit conventions, and deployment checklist
- `agents/CLAUDE.md` - project-specific guidance and gotchas
- `agents/REPLIT.md` - Replit environment, config, and secrets guidance

This document explains the repository workflow and practical rules for maintaining the bot code.
It is intentional, project-specific guidance for contributors and agents.

## Branching

- `main` - production-ready code only
- `feat/<short-description>` - new features
- `fix/<short-description>` - bug fixes
- `refactor/<short-description>` - refactors and cleanup

Only merge to `main` after the bot starts cleanly and the test suite passes.

## Configuration

All runtime configuration comes from `config.env`.
Do not commit `config.env`; use `config.env.example` as the template.

The bot uses the following configuration sources:

- `tcbot/__init__.py` loads `config.env`
- `cfg` is the global configuration adapter used by modules
- `MODULES_LOAD` and `MODULES_NO_LOAD` control module discovery

## Adding a new module

When adding a new file under `tcbot/modules/`:

- Add `from __future__ import annotations`
- Add the copyright header and a one-line module docstring
- Define `__module_name__` or `__module_name__ = None`
- Define `__help_text__` if the module is visible to users
- Build `__handlers__` at the bottom of the file
- Add the module to `MODULES_LOAD` only when the file is ready for review

Every command handler and inline-keyboard callback in the module **must** carry `@decorators.ratelimiter(limit, period)` as the outermost decorator. See `agents/STYLE-CODE.md` for the full decorator stack order and the standard rate-limit table. Message-event handlers (e.g. `on_new_member` in `greeting.py`) are exempt.

If ordering matters, adjust `_PRIORITY_FIRST` or `_PRIORITY_LAST` in `tcbot/modules/__init__.py`.

## Adding a database collection

When adding a new database helper under `tcbot/database/`:

1. Create `tcbot/database/<name>_db.py` with an async private `_col()` accessor
2. Expose the module in `tcbot/database/__init__.py`
3. Keep all helpers async and typed
4. Avoid raw `col()` calls outside the database layer

## Testing

Run unit tests with:

```bash
python3 -m pytest tests/ -q
```

The test suite is designed to run offline, without a bot token or MongoDB connection.

## Bot startup verification

Use:

```bash
python3 -m tcbot
```

Confirm the bot starts without import errors and the Flask keepalive thread starts on port `5000`.

## Documentation and style

The authoritative documentation is in `docs/` and `agents/`.
Use `docs/index.md` as the navigation hub.

When working on code, follow the style rules in `agents/STYLE-CODE.md` and `agents/STYLE-COMMENTS.md`.

## Related documentation

- [Documentation hub](index.md)
- [Project architecture](architecture.md)
- [Modules and service boundaries](modules.md)
- [Conversation flows and workflows](workflows.md)
- [AI / agent guidelines](agent-guidelines.md)
- [Agent instructions for Claude](../agents/CLAUDE.md)
- [Replit environment notes](../agents/REPLIT.md)
- [Code style guidelines](../agents/STYLE-CODE.md)
- [Comment style guidelines](../agents/STYLE-COMMENTS.md)
- [Workflow expectations](../agents/WORKFLOW.md)
- [Project rules and constraints](../agents/RULES.md)
