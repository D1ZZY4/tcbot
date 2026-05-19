# AI / Agent Guidelines - TCF Bot

This page clarifies how AI agents and reviewers should interpret repository documentation.
It is written to complement the `agents/` guidance, so read the project-specific agent docs before acting.
- `agents/RULES.md` - coding conventions, what is forbidden
- `agents/STYLE-CODE.md` - code style, typing, and formatting rules
- `agents/STYLE-COMMENTS.md` - comment and docstring style
- `agents/WORKFLOW.md` - branching, commit conventions, and deployment checklist
- `agents/CLAUDE.md` - project-specific guidance and gotchas
- `agents/REPLIT.md` - Replit environment, config, and secrets guidance

This document is intended to help AI agents and human reviewers understand the repository context.
It describes the authoritative sources, the repository scope, and the code areas that matter most.

## Source of truth

The primary codebase is:

- `tcbot/` - bot runtime logic, command modules, helper utilities, and workflows
- `tests/` - unit tests that verify helper logic and important behaviors
- `agents/` - style, comment, workflow, and rule guidance for code contributions
- `README.md` - project overview, quick start, and environment variables

Do not treat `.github/` as the primary source for bot architecture. `.github/` contains CI workflow definitions, which are secondary to the actual application code.

## What an agent should use first

1. `docs/index.md` - documentation hub and navigation
2. `docs/architecture.md` - overall system architecture and runtime flow
3. `docs/modules.md` - module discovery, boundaries, and helper packages
4. `docs/workflows.md` - conversational workflow structure and conventions
5. `docs/development.md` - repository workflow, configuration, and tests
6. `agents/STYLE-CODE.md` and `agents/STYLE-COMMENTS.md` - coding and comment conventions
7. `agents/WORKFLOW.md` and `agents/RULES.md` - project workflow expectations and constraints

## Key repository focus

- The bot is built with `python-telegram-bot` v22 and Motor for async MongoDB.
- `tcbot.__main__` is the startup entry point.
- `cfg` is the central config accessor.
- The database layer is asynchronous and is intended to isolate MongoDB collection access.
- Conversation flows live entirely in `*_flow.py` files. There are **no** `*_conv.py` files.
  `reason_flow.build_modaction_conv()` is the central `ConversationHandler` factory for kick,
  mute, and warn. Ban uses its own album-aware proof flow in `ban_flow.py`.
  `appeal_flow.py` is a standalone handler independent of `reason_flow`.

## Project-specific constraints

- Keep configuration isolated to `config.env` and `config.env.example`.
- Use `parse()` helpers and the `cfg` adapter for runtime configuration.
- All database helpers must be async and typed.
- Handlers should not use raw MongoDB collection access outside database modules.
- Command modules should expose `__handlers__`, `__module_name__`, and `__help_text__` when visible.
- Every command handler must carry `@decorators.ratelimiter(limit, period)` as the outermost decorator.
  Message-event handlers (e.g. `on_new_member`) are exempt.

## Helpful links

- [Documentation hub](index.md)
- [Project architecture](architecture.md)
- [Modules and service boundaries](modules.md)
- [Conversation flows and workflows](workflows.md)
- [Development workflow and onboarding](development.md)
- [Agent instructions for Claude](../agents/CLAUDE.md)
- [Replit environment notes](../agents/REPLIT.md)
- [Code style guidelines](../agents/STYLE-CODE.md)
- [Comment style guidelines](../agents/STYLE-COMMENTS.md)
- [Project rules and constraints](../agents/RULES.md)
