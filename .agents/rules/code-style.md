# Code Style and Architecture Rules

This file defines Python coding standards, module boundaries, application architecture, handler safety, database access, localization, workflows, and runtime behavior for TCF Bot.

The goal is to maintain a consistent, modular, maintainable, and predictable codebase without unnecessary abstractions or duplicated responsibilities.

Authorization and secret handling live in [`security-rules.md`](security-rules.md), concurrency and asynchronous execution patterns live in [`asyncio-gather-rules.md`](asyncio-gather-rules.md), validation and tool requirements live in [`docs/operations/ci-cd.md`](../../docs/operations/ci-cd.md), and comments and Markdown conventions live in [`comment-style.md`](comment-style.md).

This file owns code and architecture conventions. Referenced documents own their respective specialized requirements.

---

## Language and File Structure

- Use Python 3.14 syntax and four-space indentation.
- Every Python module must start with the project copyright header, followed by a one-line module docstring and `from __future__ import annotations` as the first non-comment code statement.
- Use two blank lines between top-level functions and classes after formatting.
- Prefer focused functions, explicit responsibilities, and early returns over deeply nested conditionals.
- Keep every Python source file at or below 1,000 lines. Treat this as a hard limit, not a target to fill.
- When a module exceeds the file budget, split it into a same-named package containing focused submodules.
- Preserve the existing public import surface through a thin `__init__.py` that re-exports the exact public API. Existing dotted import paths must remain stable unless an intentional migration is documented.
- Keep source compatible with the Ruff configuration in `pyproject.toml`.

Example module header:

```python
# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Federation ban commands and handler registration."""

from __future__ import annotations
```

### Module Design

- Give each module one clear, cohesive responsibility.
- Keep related functionality close to the domain that owns it.
- Prefer extending an existing module or helper over introducing a parallel abstraction.
- Split oversized modules by responsibility, not merely to reduce line counts.
- Avoid circular imports, unnecessary compatibility wrappers, and excessive re-export layers.
- Keep package initialization lightweight and predictable.
- Preserve established public interfaces unless a deliberate change is required.

---

## Imports

Order imports as follows:

1. `from __future__ import annotations`
2. Standard library.
3. Third-party packages.
4. Internal `tcbot.*` imports.

Rules:

- Use one blank line between import groups.
- Do not use wildcard imports.
- Do not use inline imports inside functions.
- Let Ruff's `I` rules handle import sorting. Do not fight the formatter with manual spacing.
- Prefer `from tcbot import cfg` for configuration.
- Prefer `from tcbot import database as db` in feature modules.
- Do not import raw environment variables outside `tcbot/__init__.py`.
- Avoid importing implementation details from unrelated feature modules when a shared owning module already exposes the required interface.
- Remove unused and redundant imports.

---

## Typing and Naming

### Type Annotations

- Prefer built-in generics such as `list[str]`, `dict[str, int]`, and `int | None`.
- Prefer `collections.abc` for callable and iterable abstractions.
- Use `TypedDict` document shapes from `tcbot/database/documents.py`.
- Use `NewType` primitives from `tcbot/database/types.py` when the database API already uses them.
- Public functions and methods require explicit parameter and return types.
- Use `str | None`, not `Optional[str]`.
- Prefer built-in generics over legacy typing aliases.
- Return `None` explicitly for not-found lookups when that is the declared contract.
- Keep handler return types as `None` unless the framework requires otherwise.
- Do not use `Any` as a shortcut for unclear data shapes.
- Do not use `cast()` to silence a problem that should instead be modeled, validated, or checked.
- Model external and untrusted data explicitly before using it in domain logic.
- Keep annotations consistent with actual runtime behavior.

### Naming

- Use `_snake_case` for private helpers and `_UPPER_CASE` for private constants.
- Use `snake_case` for public functions and variables.
- Use `PascalCase` for classes.
- Use uppercase `SNAKE_CASE` for public constants.
- Name asynchronous command handlers `cmd_*`.
- Name event and callback handlers `on_*`.
- Name conversation states `WAITING_*`.
- Use descriptive names that communicate domain meaning and responsibility.
- Avoid abbreviations unless they are established project terminology.

---

## Code Quality and Design

### Simplicity and Maintainability

- Prefer straightforward solutions over unnecessary abstraction.
- Keep functions focused and responsibilities explicit.
- Extract shared renderers, parsers, keyboards, database helpers, and workflows instead of duplicating logic.
- Keep one source of truth for cross-cutting behavior.
- Extend the existing owning helper or domain module before creating another utility or parallel abstraction.
- Avoid premature generalization, speculative extensibility, and unnecessary indirection.
- Do not introduce layers that only forward calls without providing meaningful ownership or behavior.
- Keep interfaces small and explicit.
- Avoid coupling unrelated modules through internal implementation details.

### Consistency

- Follow established project naming, structure, import, typing, and formatting conventions.
- Prefer consistency with the existing architecture over introducing a second pattern for the same responsibility.
- When changing an established pattern, update its consumers and relevant documentation.
- Do not maintain multiple competing sources of truth for configuration, workflow state, formatting, or domain behavior.

### Dead Code and Duplication

- Remove unused imports, variables, functions, classes, and commented-out code.
- Do not retain obsolete compatibility paths without a documented requirement.
- Never remove meaningful functionality merely to silence a diagnostic.
- Do not duplicate business rules, validation logic, state transitions, or message construction.
- Keep comments and docstrings accurate when behavior changes.

### Error Handling and Logging

- Do not use bare `except:`.
- Never swallow exceptions with `except Exception: pass`.
- Catch specific exceptions whenever practical.
- Use explicit fallback behavior only when it is appropriate for the affected operation.
- Use module loggers instead of `print()` in application code.
- Log I/O failures with actionable context.
- Use `try/except` at Telegram and database I/O boundaries where failures must be handled.
- Do not hide unexpected failures behind silent defaults.
- Keep one failed group from aborting a multi-group operation.

Detailed failure propagation, concurrency, cancellation, and timeout behavior follow [`asyncio-gather-rules.md`](asyncio-gather-rules.md).

---

## Telegram Messages and Handlers

### Message Formatting

- Bot messages render in the viewer's locale, with `en-US` as the default locale.
- User-facing messages use `parse_mode="MarkdownV2"`.
- Never use HTML parse mode.
- Never hardcode user-facing wording in Python. Follow the [Internationalization](#internationalization-i18n) rules.
- Escape user-provided text with `esc()`.
- Use `user_ref()` for clickable user names.
- Use `code()` for IDs.
- Use `bold()` for static bold labels.
- Do not combine `user_ref(x)` and `code(x)` for the same value.
- Keep bot replies professional, friendly, concise, and lightly humorous.
- Pictograph emoji and text emoticons are forbidden in bot replies and audit logs.

### Handler Decorator Order

Command and callback handlers use this decorator order:

```python
@decorators.ratelimiter(limit=5, period=60)
@decorators.mod_only
@decorators.log_execution
async def cmd_example(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    ...
```

Rules:

1. `ratelimiter()` is outermost.
2. The required authorization guard is second.
3. `log_execution` is innermost.
4. Message-event handlers are exempt from per-handler rate-limit decorators.
5. Use `owner_only` for Founder-only actions, `staff_only` for Founder/Admin actions, `mod_only` for federation moderation, and `basic_mod_only` for kick, mute, and warn.
6. Always call `await q.answer()` before performing other callback-query work.
7. Never use private PTB attributes such as `q._bot`; use `ctx.bot`.
8. Do not retain `Update`, `Message`, or `CallbackQuery` objects beyond the handler call lifetime.
9. Wrap repeated Telegram calls so one failure does not stop a multi-target operation.
10. Use `tcbot.utils.dispatch.fan_out()` for multi-group Telegram operations.

Concurrency and failure-count details belong in [`asyncio-gather-rules.md`](asyncio-gather-rules.md).

Follow [`security-rules.md`](security-rules.md) for authorization, ownership checks, and sensitive operations.

---

## Internationalization (i18n)

User-facing strings live in `i18n/<locale>/*.toml`, with `en-US` as the source of truth.

Python code retrieves localized messages through `t()` and must not embed wording for localized surfaces.

The translator contract lives in [`i18n/README.md`](../../i18n/README.md). The user-facing feature guide lives in [`docs/features/language.md`](../../docs/features/language.md).

### Locale Resolution and Threading

- Resolve the locale once per handler using `helper.locale.locale_for_update(update)`.
- Private chats use the sender's locale.
- Groups use the group locale.
- Direct messages to one user use `locale_for_user`.
- Updateless event paths use `locale_for_chat`.
- Locale resolution must not raise.
- Pass the resolved locale explicitly to every `t()` call.
- The default locale is for tests and golden checks, never as a shortcut in handlers.
- Flows carry the moderator locale in conversation state using `{action}_locale` keys.
- Resolve the target user's locale freshly for direct messages.
- Audit-log channel posts, staff operational messages, and infrastructure error reports remain English by design.

### Templates and Placeholders

- Write raw TOML template text without manually adding MarkdownV2 escape backslashes. The rendering engine escapes text at render time.
- Keep one translation file per domain, such as `banning.toml` and `kicking.toml`.
- Button labels live exactly once in `button.toml`.
- Match the rendering mode to the actual send path.
- Use `plain=True` for alerts and replies sent with `parse_mode=None`.
- Use the default rendering mode for MarkdownV2 sends.
- A rendering-mode mismatch can expose raw escape characters or break message parsing.
- Pass dynamic values as raw data so the rendering engine can escape them.
- Use `Safe` only for explicitly preformatted markup produced by trusted formatting helpers such as `user_ref()`, `code()`, and `bold()`.
- Never pre-escape data that the rendering engine will escape.
- Never pass a rendered string as an ordinary plain placeholder.
- Use bare placeholder names such as `{user}` and `{count}`.
- Do not use format specifications or conversions in placeholders.
- Do not place placeholders inside mini-markup spans such as backtick code or asterisk bold spans. Keep markup balanced and unnested. Compose markup around dynamic values with `Safe` in Python instead.
- Keep placeholder sets identical across locales. Mismatches are invalid.

### Help and Keyboards

- Every module exposes `get_help(locale)` returning its `HelpEntry`.
- Keep `__help__` as the default-locale entry for tests and fallbacks.
- The `help.py` module rebuilds content per request so topics, overviews, sections, and keyboards follow the requesting user's locale.
- Section labels and scope bodies are shared through `common.toml` sections such as `[section]`, `[context]`, and `[target]`.
- Section labels render as raw text, while section bodies render as MarkdownV2.
- Use `who_section`, `where_section`, and `target_section` with the resolved locale.
- Every locale-dependent keyboard builder in `keyboards/` takes `locale` and reads button labels from `button.toml`.
- `help_topics_kb` is locale-independent.
- Thread the handler locale through every relevant call site.

---

## Database and Cache Access

- Keep all database writes and table access in `tcbot/database/` helpers.
- Feature and command modules must not build SQLAlchemy statements directly or perform raw insert, update, or delete operations.
- Place new database concerns in descriptive `*_db.py` modules.
- When a database module exceeds the file budget, split it into a same-named `*_db/` package following the module-splitting rules.
- Add indexes for new tables and index-sensitive queries in `tcbot/database/base.py`, and ship an Alembic revision with them.
- Keep database helpers asynchronous and fully typed.
- Invalidate relevant caches after cache-sensitive writes.
- Use `documents.py` for document shapes and `Literal` aliases.
- Use `types.py` for domain primitive types.
- Do not rename or delete stored fields without a migration plan and updates to every affected read path.
- Keep database access, persistence rules, and document ownership within the database layer.

---

## Conversation Flows and Keyboards

### Conversation Flows

- Conversation handlers live in `tcbot/modules/helper/pipelines/`.
- Flow files use the `*_flow.py` suffix.
- Keep flow files within the file budget.
- Split an oversized flow into a same-named `*_flow/` package with focused submodules.
- Preserve existing public import paths through the package's `__init__.py`.
- Never create `*_conv.py` files.
- Kick, mute, and warn use `reason_flow.build_modaction_conv()`.
- Ban uses `ban_flow.ban_conversation()`.
- Appeals use the `appeal` singleton from `appeal_submit_flow.py` and its `BuildAppeal` builder.
- Every flow must have a cancellation fallback.
- Use `WAITING_*` state constants.
- Use `cfg.album_debounce` and other `cfg` values for workflow deadlines. Never hardcode workflow timing literals when a project configuration value exists.

### Keyboards and Formatting

- Define inline keyboard builders only in `tcbot/modules/helper/keyboards/`.
- Use formatter helpers from `tcbot/utils/formatter.py`.
- Reuse existing keyboard and formatting helpers rather than duplicating button construction or formatting behavior.
- Keep keyboard construction separate from conversation-state management.
- Pass locale explicitly to locale-dependent keyboard builders.

---

## Datetime Handling

- Do not use `datetime.utcnow()`.
- Do not inline `datetime.now(timezone.utc)` outside `tcbot.utils.time_and_date`.
- Use `utc_now()` for database timestamps and elapsed-time checks.
- Use `to_utc(dt)` before arithmetic when a database value may be naive.
- Use `fmt_dt(dt)` or `utc_now_str()` for user-visible timestamps.
- Keep timezone conversion and formatting centralized in `tcbot.utils.time_and_date`.
- Do not mix naive and aware datetimes in comparisons or arithmetic.

Concurrency, `asyncio.gather()`, fan-out, timeouts, and cancellation follow [`asyncio-gather-rules.md`](asyncio-gather-rules.md).

---

## Runtime Architecture

### Application Startup

- `tcbot/__main__.py` owns application startup, Flask keep-alive startup, handler registration, database initialization, error reporting, and transport.
- Keep application lifecycle responsibilities centralized.
- Preserve explicit PTB lifecycle management and scheduler readiness behavior.
- Webhook transport is the production path.
- Local development without a public URL may fall back to polling.
- Avoid introducing a second startup or transport ownership path.

### Modules and Discovery

- `tcbot/modules/__init__.py` owns module discovery.
- Keep the `MODULES_LOAD` and `MODULES_NO_LOAD` filters centralized there.
- Do not duplicate module discovery or loading decisions in individual feature modules.

### Messaging and Persistence

- Handlers use database helpers instead of direct collection access.
- Cross-group actions use the bounded dispatch helper.
- Keep webhook enqueue failures retryable by returning HTTP `503`.
- Preserve FIFO Redis mutations.
- Preserve the Redis `v2` namespace and typed JSON values.
- Use `clear_all()` for prefix-wide cache invalidation.
- Use `clear()` only for L1 invalidation.
- Do not change established storage or cache semantics without a deliberate migration and compatibility plan.

---

## Dependency Management

- Declare project dependencies in `pyproject.toml`.
- Update `uv.lock` through `uv` whenever dependencies or dependency metadata change.
- Do not install or manage project dependencies through a separate package manager.
- Prefer existing dependencies and standard-library functionality when they satisfy the requirement.
- Evaluate maintenance, compatibility, security, and runtime impact before introducing a dependency.
- Avoid adding dependencies for trivial functionality that can be implemented clearly with existing project facilities.
- Do not leave unused dependencies after removing their consumers.

---

## Non-Negotiable Restrictions

The following patterns are forbidden:

- Creating `*_conv.py` files.
- Writing to the database from command or feature modules.
- Adding keyboard builders outside `tcbot/modules/helper/keyboards/`.
- Using HTML parse mode.
- Duplicating reason or proof workflow state handlers.
- Calling raw `col()` from feature modules.
- Leaving dead or commented-out code.
- Swallowing exceptions silently.
- Adding dependencies without updating `pyproject.toml` and `uv.lock` through `uv`.
- Editing secrets or unrelated project files during a scoped task.
- Using sequential awaits for independent operations.
- Inlining self, bot, Telegram, Founder, or staff branches instead of using `identity.classify`.
- Hardcoding localized user-facing wording in Python instead of the `i18n/` catalog, except for sanctioned audit logs, staff operational messages, and infrastructure error reports.
- Passing rendered strings as plain non-`Safe` placeholders.
- Placing placeholders inside mini-markup spans.
- Hardcoding bot tokens, database URIs, passwords, API keys, webhook secrets, deployment chat IDs, or other credentials.

Security-sensitive restrictions and authorization requirements are governed by [`security-rules.md`](security-rules.md).

The global em dash prohibition is governed by [`comment-style.md`](comment-style.md).

---

## Final Principles

- Keep architecture modular without introducing unnecessary complexity.
- Keep each responsibility in its owning module or layer.
- Prefer one clear implementation over multiple competing abstractions.
- Preserve existing public interfaces unless a deliberate change is required.
- Make failures observable and handle them at appropriate boundaries.
- Keep asynchronous operations safe, bounded, and predictable.
- Maintain consistent typing, naming, formatting, and module structure.
- Update relevant documentation when architecture, behavior, paths, or public interfaces change.
- Never compromise correctness or maintainability merely to satisfy a superficial style preference.

The codebase should remain understandable, consistent, and maintainable as functionality grows.
