---
name: docs-maintainer
description: Update and review project Markdown documentation so root docs, agent docs, docs indexes, detailed guides, setup instructions, and local skill docs stay accurate and English-only.
---
Last updated: 2026-05-28


# Docs Maintainer

Use this skill when the user asks to update, fill in, review, or reorganize Markdown documentation for this project.

## Scope

Documentation normally lives in:

- root docs: `README.md`, `AGENTS.md`, `PLAN.md`, `replit.md`
- agent/contributor rules: `agents/*.md`
- developer docs: `docs/**/*.md`
- project-local skills: `agents/skills/**/SKILL.md` when the task explicitly mentions skills

Do not edit `config.env` while doing documentation maintenance unless the user explicitly asks.

## Documentation Standards

Write in clear English with a professional, friendly tone. Be practical and direct, not overly formal.

Good documentation should:

- describe current behavior, not planned behavior unless clearly marked,
- link to related docs using relative paths,
- avoid real tokens, MongoDB URIs, private credentials, or sensitive chat IDs,
- use code blocks for commands, env examples, and file-layout examples,
- keep user-facing setup steps separate from agent-only rules,
- mention validation commands when they matter,
- avoid stale references to files that do not exist.

## Project Facts To Keep Current

As of 2026-05-28, TCF Bot uses:

- Python 3.12 project target
- `python-telegram-bot[job-queue] == 22.5`
- Motor/MongoDB
- Flask keep-alive server
- `uv` and `uv.lock`
- Ruff
- pytest + pytest-asyncio offline tests

Core commands:

```bash
uv sync
uv sync --extra test
uv run --extra test pytest tests/ -q
uv run --extra test pytest --collect-only -q
uv run ruff check .
uv run ruff format .
python -m tcbot
```

## Update Workflow

1. Inventory the requested Markdown files.
2. Check current repository structure before documenting paths.
3. Inspect relevant code or config templates only as needed.
4. Update docs with minimal but complete edits.
5. Update indexes when adding a new documentation file.
6. Search for stale links or old filenames.
7. Run lightweight validation.

Suggested validation:

```bash
git --no-pager diff --check
uv run --extra test pytest --collect-only -q
```

For docs-only changes, full test execution is usually not required unless documentation examples depend on generated code or test inventory.

## Detailed Guides

When updating `docs/*-detailed.md`, include:

- purpose and ownership,
- commands/callbacks involved,
- user flow and staff flow,
- database impact,
- logging behavior,
- edge cases,
- test scenarios or validation hints.

For current detailed feature docs, keep these topics accurate:

- appeal submissions happen in bot DM through deep links,
- `#appeal` matching is case-insensitive,
- ban proof is required,
- warnings are per-group,
- warn-limit auto-ban clears warnings only after successful ban,
- role checks use canonical role helpers.

## Final Response

Summarize updated docs by category, mention validation, and clearly note any files intentionally skipped such as `config.env`.
