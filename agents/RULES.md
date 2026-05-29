# Project Rules — TCF Bot

Read [`CLAUDE.md`](CLAUDE.md) first. This file lists hard constraints for all AI agents and maintainers. These rules apply to code, tests, documentation, and configuration unless a task explicitly narrows the allowed scope.

For code style enforcement, see [`STYLE-CODE.md`](STYLE-CODE.md). For comment conventions, see [`STYLE-COMMENTS.md`](STYLE-COMMENTS.md). For development workflow, see [`WORKFLOW.md`](WORKFLOW.md). For testing and validation commands, see [`TEST-RUFF.md`](TEST-RUFF.md).

---

## Mandatory Read-Before-Work and Update-After-Work

These two rules are non-negotiable and apply to every task. The user should NEVER need to remind you about either.

**Before any work**, read these files at the start of every new conversation:

- [`agents/CLAUDE.md`](CLAUDE.md), [`agents/RULES.md`](RULES.md) (this file)
- [`AGENTS.md`](../AGENTS.md), [`PLAN.md`](../PLAN.md), [`CHANGELOG.md`](../CHANGELOG.md)
- The relevant files in [`agents/`](.), [`docs/`](../docs/), and the root project folder for the area you are touching.

**After any work**, in the same turn:

- Add an entry to [`CHANGELOG.md`](../CHANGELOG.md) under `[Unreleased]` (Added / Changed / Fixed / Removed / Documentation).
- Update [`PLAN.md`](../PLAN.md) when the change affects runtime, project state, priorities, or test counts.
- Update every related `docs/*.md`, `agents/*.md`, `README.md`, or `replit.md` whose content is now stale.

See the **MANDATORY** sections at the top of [`CLAUDE.md`](CLAUDE.md#mandatory-read-these-files-before-any-work) for the full read/update tables.

Skipping either step is a defect of the same severity as a failing test.

---

## Skills and Sub-Agents Policy

**Skills (`agents/skills/`) auto-invoke whenever their trigger matches.** The user does not want to type "use the X skill". If you are about to write code in `tcbot/`, the [`project-policy`](skills/project-policy/SKILL.md) skill applies. If you are about to edit docs, the [`docs-maintainer`](skills/docs-maintainer/SKILL.md) skill applies. The same is true for `telegram-bot-builder`, `mongodb-query-optimizer`, `async-python-patterns`, `python-code-quality`, `mermaid-diagrams`, `runtime-debugger`, `feature-reviewer`, and `general-sub-agent` — invoke them silently as part of doing the task, and compose multiple skills when a single task spans multiple areas. See the full table in [`CLAUDE.md`](CLAUDE.md#mandatory-auto-invoke-skills-use-sub-agents-sparingly).

**Sub-agents (`agents/agents/`) are expensive and only used when the work is genuinely heavy.** The default is to do the work yourself in the main agent. Only delegate to a sub-agent when the task is large, the scopes are genuinely independent, and the parallelism or independent-perspective value justifies the token cost. Sub-agents can drift off-task — prefer one focused main agent over many noisy sub-agents.

---

## General Constraints

1. TCF Bot is a production federation bot. Preserve backward compatibility.
2. Keep all user-facing bot messages in English.
3. Bot messages use `parse_mode="HTML"`; never use Markdown parse mode.
4. Do not edit unrelated files or refactor outside the requested task.
5. Do not remove meaningful behavior just to silence warnings.
6. Do not commit, move, print, or document real secrets.
7. `config.env` is local and gitignored. `config.env.example` uses placeholders
   only.
8. On Replit, production secrets belong in Replit Secrets.
9. Use `uv` for dependency management. Do not add dependencies to
   `requirements.txt`.

---

## Imports and Module Structure

1. Every Python module begins with the copyright header, one-line module
   docstring, then `from __future__ import annotations` as the first non-comment
   code line.
2. Import groups are ordered as future, standard library, third-party, internal
   `tcbot.*`, with one blank line between groups.
3. No wildcard imports.
4. No inline imports inside functions or handlers.
5. Prefer `from tcbot import cfg` and `from tcbot import database as db` in
   feature modules.
6. Do not import raw environment variables outside the config layer.

---

## Code Quality

1. No dead code: remove unused imports, variables, functions, and commented-out
   code.
2. No duplicate logic: extract shared renderers, parsers, keyboards, DB helpers,
   and workflows.
3. No silent fallbacks: log failures at `log.debug()` minimum.
4. No bare `except:` and no `except Exception: pass`.
5. No `print()` in application code; use module loggers.
6. Public functions and methods require type annotations.
7. Use Python 3.12 built-in generics and union syntax.
8. Keep code compatible with Ruff formatting and lint rules in `pyproject.toml`.

---

## Decorators and Authorization

Command handlers and callback handlers use decorators in this order, outermost to
innermost:

```python
@decorators.ratelimiter(limit=5, period=60)
@decorators.mod_only
@decorators.log_execution
async def cmd_example(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    ...
```

Rules:

1. `ratelimiter()` is always outermost for command/callback handlers.
2. The auth guard is second when required.
3. `log_execution` is innermost.
4. Message-event handlers are exempt from per-handler rate-limit decorators.
5. Use the correct auth guard:
   - `owner_only`: Founder-only actions.
   - `staff_only`: Founder/Admin staff actions.
   - `mod_only`: ban, unban, and federation-level moderation.
   - `basic_mod_only`: kick, mute, warn.

---

## Role System

1. Use `users_db.get_effective_role(user_id)` to resolve roles.
2. Use `users_db.can_act_on(executor_id, target_id)` or
   `decorators.resolve_and_check()` for executor-vs-target checks.
3. Never chain `is_owner()` + `is_admin()` + `get_role()` manually in handlers.
4. Never compare role ranks inline in command modules.
5. Use `ROLE_LABEL` for user-facing labels.
6. Call `Demote.execute(..., trigger="ban"|"kick")` before executing a ban or kick against a target who holds
   any role.
7. Developer and Tester roles live in `tc_roles`.
8. Admin promotion requests use `queues_db` and the existing promotion workflow.

---

## Telegram API Rules

1. Always `await q.answer()` before other callback-query work.
2. Never use private PTB attributes such as `q._bot`; use `ctx.bot`.
3. Do not store `Update`, `Message`, or `CallbackQuery` objects outside the
   handler call lifetime.
4. Wrap repeated Telegram API calls in `try/except` so one failure does not stop
   a multi-group operation.
5. Use `fan_out()` from `tcbot.utils.dispatch` for multi-group fan-out.
6. Do not send unescaped user-provided text in HTML messages.

---

## Database Rules

1. All MongoDB writes live in `tcbot/database/` helper modules.
2. Module handlers must not call `col()` directly.
3. New database concerns go in a descriptive `*_db.py` file.
4. New collections require indexes in `mongos.ensure_indexes()`.
5. Index-sensitive queries must match existing indexes.
6. All DB helpers are async and fully typed.
7. Cache-sensitive writes must invalidate the relevant cache.
8. Use `documents.py` for document shapes and Literal aliases.
9. Use `types.py` for domain `NewType` primitives.
10. Do not rename or delete stored fields without a migration plan and all
    read-path updates.

---

## Conversation Flow Rules

1. Conversation handlers live in `tcbot/modules/helper/workflows/`.
2. Flow files are named `*_flow.py`; never create `*_conv.py` files.
3. Kick, mute, and warn reuse `reason_flow.build_modaction_conv()`.
4. Ban uses `ban_flow.ban_conversation()`.
5. Appeal uses `appeal_flow.build_handler()`.
6. New standalone flows should model `appeal_flow.py`.
7. Conversation states are `WAITING_*` constants.
8. Every flow has a cancel fallback.
9. Timeouts use `cfg.proof_timeout` or `cfg.appeal_timeout`, not hardcoded
   integers.

---

## Keyboards and Formatting

1. All inline keyboard builders live in `tcbot/modules/helper/keyboards.py`.
2. Do not define keyboard factory functions inside command modules.
3. Use formatter helpers from `tcbot/modules/helper/formatter.py`:
   - `esc()` for user-provided strings.
   - `mention()` for user links.
   - `code()` for IDs and identifiers.
   - `bold()` for static bold text.
4. Use parenthesized multi-line strings for message text.
5. Do not combine `mention(x)` and `code(x)` for the same value.

---

## Datetime Rules

1. Do not use `datetime.utcnow()`.
2. Do not inline `datetime.now(timezone.utc)` outside
   `tcbot.utils.timedate_format`.
3. Use `utc_now()` for DB timestamps and elapsed-time checks.
4. Use `to_utc(dt)` before datetime arithmetic if a DB value may be naive.
5. Use `fmt_dt(dt)` or `utc_now_str()` for user-visible time strings.

---

## Async Rules

1. All DB operations are async.
2. Do not call `asyncio.run()` inside handlers.
3. Use `asyncio.gather()` for independent async operations.
4. Use `fan_out()` for multi-group Telegram operations.
5. Do not create untracked background tasks unless they are supervised and errors
   are logged or reported.

---

## Testing and Validation

1. Run focused tests for changed behavior when possible.
2. Run the full suite before merging code changes:

   ```bash
   python3 -m pytest tests/ -v
   ```

3. Run Ruff before finalizing code changes:

   ```bash
   uv run ruff format .
   uv run ruff check --fix .
   ```

4. Do not claim validation passed unless the command actually ran and passed.
5. Tests must be offline and must mock Telegram/MongoDB/network dependencies.

---

## Security Rules

1. Never hardcode bot tokens, MongoDB URIs, passwords, API keys, or webhook
   secrets.
2. Never add real secrets to docs, tests, code comments, examples, or logs.
3. Never commit `config.env`.
4. Do not expose internal IDs or links in public messages beyond what the feature
   requires.
5. Appeal links are single-use and tied to a specific `ban_id`; validate the
   current user before allowing an appeal.

---

## Forbidden Actions

- Creating `*_conv.py` files.
- Writing to MongoDB from command modules.
- Adding keyboard builders outside `keyboards.py`.
- Using Markdown parse mode.
- Duplicating reason/proof workflow states.
- Using raw `col()` in modules.
- Leaving dead or commented-out code.
- Swallowing exceptions silently.
- Adding dependencies without updating `pyproject.toml` and `uv.lock` through
  `uv`.
- Editing secrets or unrelated project files during a scoped task.
- Pictograph emoji in any bot reply or audit log message (waving hands, party poppers, prohibition signs, warning signs, etc.).
- Sequential awaits when the operations are independent — must use `asyncio.gather`.
- Inlining self / bot / Telegram / Founder / staff branches in command handlers — must use `identity.classify`.

---

## Bot Voice and Replies

1. Bot replies are professional + friendly + lightly humorous. Plain text, no exclamation cascades.
2. Pictograph emoji are forbidden in any bot output. Strip on sight.
3. Text emoticons (`:)`, `:v`, `:')`, `:D`) are allowed at most one per reply and only in witty refusal paths — never in success / error / data views.
4. Self / bot / Telegram / Founder / staff branches must use `tcbot.modules.helper.identity.classify` plus `identity.refuse_message` / `identity.staff_notice`. Do not duplicate target-type branches inline.
5. New refusal copy belongs in `identity.py`, not in `modules/*.py`.

---

## Async / Parallelism

1. Independent awaits must be combined with `asyncio.gather`. Sequential awaits are a defect.
2. External Telegram lookups (`bot.get_chat`, etc.) must be wrapped in `asyncio.wait_for(timeout=...)`.
3. Fan-out writes (DMs, logs, per-chat enforcement) use `asyncio.gather(..., return_exceptions=True)`.
4. Pre-resolve per-item lookups for paginated views before the formatting loop runs.

---

## Always Update Docs After Refactors

1. After every rename / move / replace, grep the repo for the old name and update every match in `docs/`, `agents/` (including `agents/skills/` and `agents/agents/`), `PLAN.md`, `AGENTS.md`, and `README.md` in the same change.
2. New features ship with their `docs/<feature>-detailed.md` and a row in `docs/README.md`.
3. Removed APIs lose every doc reference; no "see also" stubs to vanished symbols.
4. Restart the bot and confirm clean startup before declaring done.
