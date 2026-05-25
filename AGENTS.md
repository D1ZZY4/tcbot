# Project Overview and Repository Details

## Project Structure & Module Organization
tgbot_tcf or root project folder/
│   .gitignore
│   .replit
│   AGENTS.md
│   config.env
│   config.env.example
│   docker-compose.yml
│   Dockerfile
│   LICENSE
│   PLAN.md
│   pyproject.toml
│   README.md
│   replit.md
│   skills-lock.json
│   uv.lock
│   
├───.agents
│   └───skills
│       ├───async-python-patterns
│       │   │   SKILL.md
│       │   │   
│       │   └───references
│       │           details.md
│       │           
│       ├───mermaid-diagrams
│       │   │   README.md
│       │   │   SKILL.md
│       │   │   
│       │   └───references
│       │           advanced-features.md
│       │           architecture-diagrams.md
│       │           c4-diagrams.md
│       │           class-diagrams.md
│       │           erd-diagrams.md
│       │           flowcharts.md
│       │           sequence-diagrams.md
│       │           
│       ├───mongodb-query-optimizer
│       │   │   SKILL.md
│       │   │   
│       │   └───references
│       │           aggregation-optimization.md
│       │           antipattern-examples.md
│       │           core-indexing-principles.md
│       │           update-query-examples.md
│       │           
│       ├───project-policy
│       │       SKILL.md
│       │       
│       ├───python-code-quality
│       │       REFERENCE.md
│       │       SKILL.md
│       │       
│       └───telegram-bot-builder
│               SKILL.md
│               
├───.github
│   │   dependabot.yml
│   │   
│   └───workflows
│           codeql.yml
│           run-bot.yml
│           run-tdd.yml
│           verification.yml
│           
├───.trae
│   ├───rules
│   └───skills
│       ├───async-python-patterns
│       │   │   SKILL.md
│       │   │   
│       │   └───references
│       │           details.md
│       │           
│       ├───mermaid-diagrams
│       │   │   README.md
│       │   │   SKILL.md
│       │   │   
│       │   └───references
│       │           advanced-features.md
│       │           architecture-diagrams.md
│       │           c4-diagrams.md
│       │           class-diagrams.md
│       │           erd-diagrams.md
│       │           flowcharts.md
│       │           sequence-diagrams.md
│       │           
│       ├───mongodb-query-optimizer
│       │   │   SKILL.md
│       │   │   
│       │   └───references
│       │           aggregation-optimization.md
│       │           antipattern-examples.md
│       │           core-indexing-principles.md
│       │           update-query-examples.md
│       │           
│       ├───python-code-quality
│       │       REFERENCE.md
│       │       SKILL.md
│       │       
│       └───telegram-bot-builder
│               SKILL.md
│               
├───.vscode
│       launch.json
│       settings.json
│       
├───agents
│       CLAUDE.md
│       REPLIT.md
│       RULES.md
│       STYLE-CODE.md
│       STYLE-COMMENTS.md
│       TEST-RUFF.md
│       WORKFLOW.md
│       
├───docs
│   │   appeal-detailed.md
│   │   banning-detailed.md
│   │   button-styles.md
│   │   development.md
│   │   git-commit.md
│   │   mapping.md
│   │   README.md
│   │   role-detailed.md
│   │   workflows.md
│   │   
│   ├───databases
│   │       databases.md
│   │       
│   ├───helper
│   │       helper.md
│   │       
│   ├───modules
│   │       modules.md
│   │       
│   ├───utils
│   │       utils.md
│   │       
│   └───workflows
│           workflows.md
│           
├───tcbot
│   │   alive.py
│   │   __init__.py
│   │   __main__.py
│   │   
│   ├───database
│   │       admins_db.py
│   │       bans_db.py
│   │       cache.py
│   │       documents.py
│   │       groups_db.py
│   │       kicks_db.py
│   │       mongos.py
│   │       mutes_db.py
│   │       queues_db.py
│   │       roles_db.py
│   │       types.py
│   │       users_db.py
│   │       warns_db.py
│   │       __init__.py
│   │       
│   ├───modules
│   │   │   about.py
│   │   │   additional.py
│   │   │   admins.py
│   │   │   appeals.py
│   │   │   banning.py
│   │   │   broadcasting.py
│   │   │   checking.py
│   │   │   connecting.py
│   │   │   disconnecting.py
│   │   │   greeting.py
│   │   │   groups.py
│   │   │   help.py
│   │   │   kicking.py
│   │   │   maintenance.py
│   │   │   muting.py
│   │   │   privacy.py
│   │   │   start.py
│   │   │   stats.py
│   │   │   unbanning.py
│   │   │   warnings.py
│   │   │   __init__.py
│   │   │   
│   │   └───helper
│   │       │   ban_info.py
│   │       │   decorators.py
│   │       │   extraction.py
│   │       │   formatter.py
│   │       │   keyboards.py
│   │       │   parse_editmsg.py
│   │       │   parse_link.py
│   │       │   parse_logmsg.py
│   │       │   role_guard.py
│   │       │   __init__.py
│   │       │   
│   │       └───workflows
│   │               appeal_flow.py
│   │               ban_flow.py
│   │               connected_flow.py
│   │               kicking_flow.py
│   │               muting_flow.py
│   │               promote_flow.py
│   │               proof_flow.py
│   │               reason_flow.py
│   │               stats_chats_flow.py
│   │               stats_flow.py
│   │               unban_flow.py
│   │               warning_flow.py
│   │               __init__.py
│   │               
│   └───utils
│           dispatch.py
│           error_reporter.py
│           logger.py
│           prefixes.py
│           timedate_format.py
│           __init__.py
│           
└───tests
        conftest.py
        test_appeals_pure.py
        test_bans_db.py
        test_ban_flow.py
        test_config_parse.py
        test_decorators.py
        test_format.py
        test_keyboards.py
        test_log_templates.py
        test_prefix.py
        test_rate_limiter.py
        test_targets.py
        test_users_resolver.py
        test_warns_db.py
        __init__.py

Core code lives in `tcbot/`:
- Command modules in `tcbot/modules/`.
- Shared helpers in `tcbot/modules/helper/`.
- MongoDB access in `tcbot/database/`.
- Runtime utilities in `tcbot/utils/`.
- TDD tests in `tests/`. Tests are in `tests/` and run fully offline.

Project notes and agent-specific rules live in `agents/` and `docs/`.
Keep new database code in a `*_db.py` file.
Keep new conversation flows in a `*_flow.py` file.

## Build, Test, and Development Commands
- `uv sync` installs Python 3.12 dependencies from `pyproject.toml` and `uv.lock`.
- `python3 -m tcbot` starts the bot locally.
- `python3 -m pytest tests/ -v` runs the full test suite.
- `uv run ruff format .` reformats Python files with Ruff.
- `uv run ruff check --fix .` applies lint fixes and import cleanup.
- `docker-compose up --build` starts the bot plus a local MongoDB instance.

## Coding Style & Naming Conventions
Use Python 3.12, 4-space indentation, and `from __future__ import annotations` as the first non-comment line in every module. Ruff is the repo formatter and linter, so prefer `ruff format` for whitespace/layout and `ruff check --fix` for automatic cleanup. Prefer built-in generic types such as `list[str]` and `dict[str, int]`; avoid inline imports. Name async handlers `cmd_*` or `on_*`, conversation states `WAITING_*`, and keep module files descriptive (`banning.py`, `appeal_flow.py`). Follow the existing HTML-only bot message style and the conventions in `agents/STYLE-CODE.md`.

## Testing Guidelines
The project uses `pytest` with `pytest-asyncio`. Test files are named `test_*.py` and live under `tests/`. Prefer small, behavior-focused tests that mirror the existing offline coverage. If you change database behavior, handlers, or shared helpers, add or update tests in the matching file.

## Commit & Pull Request Guidelines
Git history uses conventional commits: `feat:`, `fix:`, `refactor:`, `docs:`, `test:`, and `chore:`. Keep commits focused and descriptive. Pull requests should summarize the change, note any config or database impact, and include test results. Add screenshots or log excerpts only for user-visible behavior changes.

## Security & Configuration Tips
Do not commit real secrets. Use `config.env` locally and Replit Secrets in hosted environments. Required values include `BOT_TOKEN` and `MONGODB_URI`. For schema changes, update all read paths and migration-sensitive code together so existing MongoDB data remains compatible.