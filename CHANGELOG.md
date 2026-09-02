# Changelog

For workflow details mentioned below, see [`docs/operations/ci-cd.md`](docs/operations/ci-cd.md). For project overview, see [`README.md`](README.md). For contributor rules, see [`AGENTS.md`](AGENTS.md).

## [Unreleased]

### Fixed

- **Correctness** (`tcbot/__init__.py`): split `except (ValueError, TypeError):` in `parse_chat_id` into two separate `except` clauses. The previous tuple form is semantically correct, but Ruff 0.16.x has a formatter bug that rewrites it to Python 2 syntax (`except ValueError, TypeError:`), which in Python 3 does not actually catch either exception -- it aliases the caught exception to the name `TypeError` and runs the body unconditionally. The split form is identical at runtime and is not affected by the formatter bug. All ruff checks (format + lint) and pyright pass; `tcbot` imports cleanly.

## [6.3.0] - 2026-09-02

### Changed

- **Dependency bump** (`uv.lock`): `cachetools` upgraded `v7.1.7` -> `v7.1.8`. Patch release, no API changes. Verified: import OK, ruff/pyright checks pass, no code changes required.

### Added

- **User mentions** (`tcbot/utils/formatter.py`): all user references now include a clickable `tg://user?id=...` link. With username: `Name | @username (tg://user?id=ID)`. Without username: `Name (tg://user?id=ID)`. The bare numeric fallback shows only the `tg://` link. This applies to welcome/greeting messages, ban/kick/mute/warn logs, check profiles, appeal messages, and all action summaries.

### Fixed

- **Correctness** (`tcbot/modules/helper/workflows/ban_flow.py`): fixed `ValueError: invalid literal for int() with base 10` crash in both new-ban and ban-update paths. The helpers `_execute_new_ban` and `_execute_ban_update` previously called `int(proof_link)` on a value that is a `t.me/c/...` URL string (built by `message_link()`), not a numeric message ID. The numeric `proof_msg_id` from `upload_proof()` was available in the caller but was discarded. Both helpers now accept `proof_msg_id: int | None` as a separate parameter, which is passed straight to `create_ban` / `update_ban`. The URL `proof_link` is retained for log text and keyboard construction, where a clickable link is required. Resolves the six repeated `_flush_album` and `on_proof_received` error reports seen between 19 Aug and 31 Aug 2026.
- **Security** (`tcbot/modules/warnings.py`): added missing `@decorators.basic_mod_only` guard on `cmd_warnlist`. Previously unguarded, allowing any group user to enumerate moderation history.
- **Correctness** (`tcbot/modules/maintenance.py`): fixed `_leave_one` success/failure classification in `cmd_leaveall`. The `isinstance(r, BaseException)` check was always False because `r` is always a tuple from `asyncio.gather`; changed to `isinstance(r[0], BaseException)` so the status message now reports accurate left/failed counts.
- **Correctness** (`tcbot/modules/start.py`): added missing `await q.answer()` in `_show_groups` early-return path when no groups are connected. Previously the Telegram loading spinner persisted indefinitely.
- **Security** (`tcbot/modules/groups.py`): replaced raw `cfg.community_name` with pre-escaped `_CNAME` constant in `cmd_tcfgroups` no-groups reply, matching the project-wide HTML escaping convention.
- **Log formatting** (`tcbot/modules/helper/parse_logmsg.py`): `User ID`, `Admin ID`, `Ban ID`, `Request ID`, and all numeric ID fields now use `<code>` formatting for consistency. `user_block` and `actor_block` docstrings updated to reflect the new format.
- **Code quality** (`tcbot/modules/helper/workflows/stats_flow.py`): added missing module-level `log` logger and added `log.debug()` for silent `get_user_mention_data()` exceptions.
- **Code quality** (`tcbot/database/warns_db.py`): added `log.exception()` in the `add_warn` rollback failure path for better observability.
- **Code quality** (`tcbot/alive.py`): replaced `datetime.now(UTC)` with project-standard `utc_now()`; removed unused `UTC`/`datetime` imports.
- **Query optimization** (`tcbot/database/bans_db.py`, `kicks_db.py`, `mutes_db.py`, `warns_db.py`, `users_cache.py`): added `_id: 0` projections to `active_bans()`, `user_bans()`, `user_kicks()`, `user_mutes()`, `get_warns()`, `user_all_warns()`, and added `_PAGE_LIMIT=200` cap with field projection to `all_users()`, reducing wire payload for list queries.
- **Query optimization** (`tcbot/database/queues_db.py`): `all_pending()` now uses a projection limiting returned fields and a `_PAGE_LIMIT=200` cap, reducing wire payload for the pending-requests list.
- **Query optimization** (`tcbot/database/warns_db.py`): `remove_last_warn()` now fetches only `{_id: 1}` for the most-recent warn lookup, making it a covered index query instead of fetching the full document.
- **Code quality** (`tcbot/modules/helper/workflows/ban_flow.py`): moved `datetime` into the `TYPE_CHECKING` block and collapsed the `if`/`else` ban_id assignment to a ternary expression, resolving TC003 and SIM108.
- **Query optimization** (`tcbot/database/mongos.py`): added compound index `[("banned_user_id", 1), ("is_active", 1), ("timestamp", -1), ("ban_id", -1)]` to serve `get_active_ban()` as a covered query (filter + sort in one index). Removed the now-redundant prefix index `[("banned_user_id", 1), ("is_active", 1)]].

### Documentation

- **Documentation** (`replit.md`): replaced verbatim `AGENTS.md` copy with actual Replit deployment guide covering secrets, run command, webhook setup, Nix config, and troubleshooting.
- **Documentation** (`docs/architecture/database.md`, `docs/operations/backup-and-restore.md`): corrected APScheduler references from `4.x`/`AsyncScheduler`/`MongoDBDataStore` to `3.11.3`/`AsyncIOScheduler`/`MongoDBJobStore` to match `pyproject.toml`.
- **Documentation** (`README.md`): corrected bot-framework stack entry to `python-telegram-bot[rate-limiter]` and removed stale "reserved for future wiring" notes from timeout descriptions.
- **Documentation** (`docs/README.md`, `docs/getting-started/setup.md`): added `--frozen` flag to `uv sync` commands to match project policy.
- **Documentation** (`docs/architecture/database.md`, `docs/features/moderation/banning.md`, `docs/operations/performance.md`): updated all `bans` index references from the removed prefix index `(banned_user_id, is_active)` to the current compound index set in `mongos.ensure_indexes()`: `(banned_user_id, is_active, timestamp desc, ban_id desc)` for `get_active_ban()`, `(is_active, timestamp desc, ban_id desc)` for `active_bans()`, and `(banned_user_id, timestamp desc, ban_id desc)` for `/check` ban history.

## [6.2.0] - 2026-08-17

### Fixed

- **Security** (`tcbot/alive.py`): remove `force=True` from `request.get_json()` in the webhook route. Flask now rejects non-`application/json` content types at the parser level, reducing the webhook attack surface without affecting legitimate Telegram delivery (which always sends `application/json`).
- **Error handler context** (`tcbot/__main__.py`): include user/chat/text context string in the console `log.error()` call for the PTB global error handler. Previously the context was only forwarded to the `error_reporter`; console logs now carry the same detail for faster debugging without waiting for the LOG_ERRORS channel.
- **Memory leak** (`tcbot/modules/helper/decorators.py`): `_RateLimiter._buckets` now performs periodic cleanup when bucket count exceeds 10,000, removing entries whose oldest timestamp is older than `window * 2`. Mirrors the Redis PEXPIRE behavior of the primary rate limiter and prevents unbounded growth during long-running sessions.
- **Dead code** (`tcbot/modules/groups.py`): removed redundant `isinstance(q.message, Message)` guard in `_toggle`. `CallbackQuery.message` is always `Message` at this call site; the check added no safety and was never triggered.
- **Type safety** (`tcbot/`): resolved all pyright type-check errors across the project (0 errors, 0 warnings). Added None guards for `effective_message`/`effective_chat`/`effective_user` in 14+ handler modules, fixed TypedDict subscript access with `.get()` fallbacks, added `cast()` expressions for `asyncio.gather` results with `return_exceptions=True`, and moved runtime-only imports into `TYPE_CHECKING` blocks in `groups.py`, `decorators.py`, and `prefixes.py`. Created `pyrightconfig.json` to pin the project venv for consistent type-checking.
- **Security** (CVE-2026-31072, `pyproject.toml`): `apscheduler==3.11.3` is flagged by GitHub Dependabot as vulnerable to RCE via insecure deserialization in `JSONSerializer`/`CBORSerializer`. This project uses `MongoDBJobStore` exclusively (no file-based job store), so the vulnerable serializers are never instantiated. The exact pin is retained as an accepted exception until APScheduler publishes a patched release; monitor PyPI for `3.11.4` or later and update promptly.
- **Correctness** (`tcbot/modules/admins.py`): `cmd_transfer` ownership transfer now calls `set_owner()` first (atomic upsert + delete_many), then `add_admin()` second inside a `try/except`. Previously `add_admin` ran first; if it succeeded and `set_owner` crashed, the federation was left ownerless. The new order guarantees the old founder stays in place on any failure.
- **Resource bounds** (`tcbot/modules/maintenance.py`): `cmd_leaveall` and `cmd_cleanup` now use `fan_out()` (semaphore-bounded to 10) instead of unbounded `asyncio.gather()`, matching the project's multi-group concurrency policy.
- **Correctness** (`tcbot/database/warns_db.py`): `clear_warns` and `clear_all_warns` return the warns delete count, not the counter delete count. The counter document delete is best-effort (the counter is rebuilt from warn history on next read); surfacing its result as the warn count was misleading.
- **Correctness** (`tcbot/database/bans_db.py`): `deactivate_ban` now uses `modified_count` instead of `matched_count`. A ban that is already inactive was incorrectly reported as "deactivated" because the filter matched but the update was a no-op.
- **Robustness** (`tcbot/__init__.py`): `parse_chat_id` wraps `int()` conversions in `try/except (ValueError, TypeError)`. A malformed env string (e.g. `abc` or `abc/def`) no longer crashes config loading; it falls back to `(0, None)` with a warning.
- **Correctness** (`tcbot/database/users_roles.py`): `get_effective_role` now re-raises DB exceptions instead of caching degraded results. Previously a transient MongoDB failure was cached as `founder`/`admin`/`None`, silently bypassing authorization checks for every subsequent call until TTL expiry.
- **Memory** (`tcbot/utils/error_reporter.py`): `_recent` dedupe dict is now capped at 1000 entries. Previously unbounded growth during error storms retained every distinct fingerprint indefinitely.
- **Search quality** (`tcbot/database/users_cache.py`): `search_by_name` regex is now anchored (`^`) so a needle like "dan" matches names that start with "dan" (e.g. "daniel") instead of names that merely contain it mid-string (e.g. "randy").
- **Correctness** (`tcbot/utils/pagination.py`): `paginate` returns an empty chunk immediately when `page_size <= 0`, preventing a division-by-zero crash from bad caller input.
- **Dead code** (`tcbot/database/documents.py`): removed unused `BanStatus` Literal alias. `RoleName` retained (used by `RoleDoc`).
- **Validation** (`.github/workflows/*`): all CI workflows now use `python-version: "3.14"` (previously `"3.12"`).
- **Tooling** (`pyproject.toml`, `pyrightconfig.json`, `.agents/skills/python-code-quality/`): added pyright to the validation pipeline alongside ruff. Updated Python target to 3.14 across project config, docs, and CI workflows.