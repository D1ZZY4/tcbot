# Development Workflow - TCF Bot

Before making any changes, **read all documentation files in the `agents/` directory** - specifically:
- `agents/RULES.md` - coding conventions, what is forbidden
- `agents/STYLE-CODE.md` - code style, typing, and formatting rules
- `agents/STYLE-COMMENTS.md` - comment and docstring style
- `agents/WORKFLOW.md` - branching, commit conventions, and deployment checklist
- `agents/CLAUDE.md` - project-specific guidance and gotchas
- `agents/REPLIT.md` - Replit environment, config, and secrets guidance

## Branching

- `main` - production-ready code only
- Feature branches: `feat/<short-description>`
- Bug fixes: `fix/<short-description>`
- Refactors: `refactor/<short-description>`

Merge to `main` only after the bot runs clean (no import errors, no tracebacks on startup).

## Making Changes

1. Read the relevant module fully before editing.
2. Check for duplicate logic across modules before adding a new function.
3. If changing a database schema (adding/removing fields), update all read paths too.
4. After editing, restart the workflow and check startup logs for import errors.

## Module Checklist

When creating a new `tcbot/modules/*.py` file:
- [ ] `from __future__ import annotations` at top
- [ ] Copyright header
- [ ] `__module_name__` set (or `None` to hide from /help)
- [ ] `__help_text__` set if `__module_name__` is not None
- [ ] `__handlers__` list at the bottom
- [ ] Module added to `_PRIORITY_FIRST` or `_PRIORITY_LAST` in `modules/__init__.py` if ordering matters

## Adding a Database Collection

1. Create `tcbot/database/<name>_db.py` with a `_col()` private accessor and async helpers
2. Import it in `tcbot/database/__init__.py`
3. All functions must be async and return typed results

## ConversationHandler Flows

All `ConversationHandler` flows live in `tcbot/modules/helper/workflows/`.

**There are no `*_conv.py` files.** Every `ConversationHandler` is built inside a `*_flow.py`
file and exposed via a factory function.

Structure:
- `*_flow.py` — executor functions, state handlers (when needed), and `ConversationHandler` factory

Central factory: `reason_flow.build_modaction_conv(action, entry_fn, executor, entry_filter, ...)`
builds the complete reason + proof `ConversationHandler` for kick, mute, and warn.
Individual flow files only define the executor adapter (`_exec_*`) and call this factory.

Ban uses its own album-aware proof flow in `ban_flow.py` (different state graph, no reason step).
`appeal_flow.py` is a standalone handler independent of `reason_flow`.

Timeout always comes from `cfg.proof_timeout` (proof flows) or `cfg.appeal_timeout` (appeal flow).

## Commit Messages

Use conventional commits:
```
feat: add /tcsweep command with SweepAgent
fix: remove dead bans variable in connected_flow
refactor: deduplicate _render() between start.py and groups.py
chore: modernize typing hints to Python 3.11 built-ins
```

## Environment

Never commit `config.env`. Use `config.env.example` as the template.
All secrets and configuration go through `config.env` exclusively. Never use Replit Secrets for this project.

## Deployment Checklist

Before pushing to production:
- [ ] Bot starts without any `ERROR` in startup logs
- [ ] `/start` shows the main menu
- [ ] `/help` lists all expected modules
- [ ] MongoDB connection confirmed in logs (`MongoDB connected → <db_name>`)
- [ ] Keep-alive Flask server on port 5000 confirmed in logs

## Related documentation

- [Documentation hub](../docs/index.md)
- [Project architecture](../docs/architecture.md)
- [Modules and service boundaries](../docs/modules.md)
- [Conversation flows and workflows](../docs/workflows.md)
- [Development workflow and onboarding](../docs/development.md)
- [AI / agent guidelines](../docs/agent-guidelines.md)
