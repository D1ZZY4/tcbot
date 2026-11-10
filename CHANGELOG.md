# Changelog

All notable changes to this project are documented here. For workflow details, see [`docs/operations/ci-cd.md`](docs/operations/ci-cd.md). For project overview, see [`README.md`](README.md). For contributor rules, see [`CONTRIBUTING.md`](CONTRIBUTING.md). For AI Agents see [`AGENTS.md`](AGENTS.md). For AI agent knowledge see [`docs/README.md`](docs/README.md).

## [Unreleased]

<details open>
<summary>Unreleased changes (click to collapse)</summary>

### Added

- **Authorization and expiry contracts are pinned** (`tests/test_moderation_contracts.py`, `tests/test_role_assignment_rules.py`): the role-rank table, the rate-limit exemption and throttle tiers, the mute expiry clauses, the atomic appeal and ban claims, the primary-group merge, the promotion rules, and the ownership transfer are covered as executable contracts. Behavior changes: none.

- **Federation log delivery has one owner** (`tcbot/modules/helper/messages/safe_edits.py`): `send_log` posts the audit log to the configured destination as MarkdownV2 in the configured thread, replacing twenty-seven hand-written copies of the same call.

- **Role sets and role labels have one owner** (`tcbot/database/users_roles.py`): `STAFF_ROLES`, `FOUNDER_ADMIN_ROLES`, and `role_label` replace eleven inline role-set literals and two different label fallbacks.

- **Name placeholders have one owner** (`tcbot/database/users_cache.py`): `is_placeholder_name` decides what counts as a real name, so the legacy `User <id>` form is no longer rendered as a name on some surfaces and not on others.

- **MongoDB query shapes are verified without a live server** (`pyproject.toml`, `uv.lock`, `tests/test_ban_uniqueness_mongo.py`): the duplicate-ban migration and the one-active-ban guarantee depend on MongoDB semantics a hand-written double cannot prove, so the in-memory MongoDB engine runs the same aggregation pipeline and the same partial unique index. Behavior changes: none; the dependency is development-only.
- **Production observability via optional extras** (`tcbot/alive.py`, `tcbot/__main__.py`, `tcbot/__init__.py`, `config.env.example`): a `/metrics` endpoint on the keep-alive server when prometheus-client is installed, the uvloop event loop policy on Linux when the package is present, and Sentry initialisation when `SENTRY_DSN` is set. Behavior changes: the operations surfaces appear only with their extras configured.

- **Property-based invariant checks** (`tests/test_property.py`): hypothesis-backed checks that `esc()` never emits an unescaped special, `parse_list` never raises, and `message_link` stays canonical. Behavior changes: none for operators.

- **Operator proof migration script** (`scripts/migrate_proofs.py`, `tests/test_proof_migration.py`, `docs/operations/proof-migration.md`): one-shot tool that copies every stored ban proof to a new channel, updates the proof ids in the bans collection, rewrites the proof buttons on the stored ban log messages, and fixes old proof links inside copied captions. Dry-run by default, resumable through a state file, album-safe. Operators point `PROOFS` at the new channel after running it.

- **Group locale change and ban-log keyboard cover** (`tests/test_group_locale_cache.py`, `tests/test_ban_log_kb.py`, `tcbot/database/groups_db.py`, `tcbot/modules/helper/keyboards/ban.py`): `set_group_locale` invalidating the groups-list cache and the merged ban-log keyboard rows are pinned. Behavior changes: none for operators.
- **Shared moderation entry sequence** (`tcbot/modules/helper/decorators/checks.py`, `tests/test_authz.py`): `resolve_mod_target` runs the locale, origin, extraction, identity, and rank steps once for the ban, kick, mute, and warn commands, replacing five copies of the same sequence. Behavior changes: none; replies and log labels are byte-identical.

- **Self-check cards stay with their owner** (`tcbot/modules/check.py`, `tests/test_checkme_owner.py`): detail and back callbacks ignore a crafted tap for another user's ban. Behavior changes: other users cannot render your ban card.

- **Module budget widened and comments tightened** (`pyproject.toml`, `.agents/rules/code-style.md`, `.agents/rules/comment-style.md`): per-file budget is 1000 lines, comments stay short and dense. Behavior changes: none for operators.

- **Runtime builder is public** (`tcbot/__main__.py`, `tcbot/serverless.py`): the shared builder, app build, and handler wiring use public names. Behavior changes: none.

- **Fresh role and connection reads for enforcement gates** (`tcbot/database/users_roles.py`, `tcbot/database/groups_db.py`, `tcbot/modules/helper/decorators/`): owner, effective-role, and connection lookups accept a fresh bypass that reads MongoDB directly and refreshes the cache. Enforcement gates use it so a demotion, transfer, or disconnect in another process is never hidden for the cache TTL; display reads keep the cached fast path. Behavior changes: demotions, transfers, and disconnects take effect immediately for moderation commands.

- **Broadcast coverage for partial failures** (`tests/test_broadcasting.py`): broadcast counting is pinned for total success and for mixed benign and transient failures. Behavior changes: none for operators.

- **Direct pymongo dependency** (`pyproject.toml`, `uv.lock`): the code imports `pymongo.errors` and `bson` in many modules, so the dependency is now declared explicitly within the major version the project already runs. Behavior changes: none; the resolved version is unchanged.

- **Authorization checks for federation origin and bot verification** (`tcbot/modules/helper/decorators/checks.py`, `tcbot/modules/helper/identity.py`, `tests/test_authz.py`): a shared origin guard requires moderation commands to start from a connected or primary group, and a tri-state bot check distinguishes a verified human from a verified bot and from an unknown lookup. The new checks fail closed on lookup failure and propagate cancellation. Behavior changes: disconnected groups are refused, and unknown ownership-transfer targets ask for a retry.

- **Local test run without CI values** (`tests/conftest.py`, `tests/test_authz.py`): the suite supplies placeholder startup values when none are present, so it collects and runs locally, and the new checks cover the fail-closed and propagation contracts. Behavior changes: none for operators.

- **Localized Prev/Next and authorization refusals** (`i18n/en-US/button.toml`, `i18n/id-ID/button.toml`, `i18n/en-US/common.toml`, `i18n/id-ID/common.toml`): the paged-list navigation row reads `button.prev` / `button.next`, and every auth refusal (tier refusals, rank, role-lookup retry, anonymous admin, outrank notice) reads `common.refuse.*` in the viewer's locale. Default-locale wording is unchanged.

- **Warn, stats, and help catalog coverage** (`i18n/en-US/stats.toml`, `i18n/id-ID/stats.toml`, `i18n/en-US/help.toml`, `i18n/id-ID/help.toml`, `i18n/en-US/common.toml`, `i18n/id-ID/common.toml`): outage cards, degraded-overview notes, localized help titles, and a shared unknown-date word in both languages. Default-locale output is unchanged.

- **Modern dependency stack for structured logging, testing, and code quality** (`pyproject.toml`, `.pre-commit-config.yaml`, `tcbot/utils/logger.py`): logging runs on `loguru` with `contextvars`-based per-request context, bridged to stdlib so capture and error shipping keep working, plus `pytest-asyncio` for proper async test execution, `pre-commit` with Ruff and pyright hooks for automated quality enforcement, and `py-spy` for production profiling. Two dependencies (`taskiq`, `pydantic-settings`) were evaluated but excluded due to Python 3.14 compatibility issues with pydantic's type evaluation internals; they will be re-added when pydantic releases a compatible version.

- **Parallel test execution** (`pyproject.toml`, `uv.lock`, `.github/workflows/test-pytest.yml`, `docs/operations/ci-cd.md`): the dev group gains `pytest-xdist` (Python 3.14 support verified upstream and by a local parallel run) and CI runs the suite with `-n auto`. All checks pass identically in serial and parallel runs. Behavior changes: none, faster feedback only.

- **Sync reconciles active mutes** (`tcbot/modules/sync.py`, `tcbot/database/scheduler.py`, `i18n/en-US/syncing.toml`, `i18n/id-ID/syncing.toml`, `docs/features/moderation/sync.md`): bare and targeted runs re-apply live mutes within the shared pair budget after the ban sweep, and the summary gains a re-muted count. Restricted non-muted users are never unrestriced. Behavior changes: sweeps now restrict seemingly-unrestricted muted members.

- **Warn auto-ban stores the warn proof on the ban record** (`tcbot/modules/helper/pipelines/warn_flow.py`, `tests/test_warn_autoban_guard.py`, `docs/features/moderation/warnings.md`): the proof upload collected with the threshold warn becomes the ban `proof_message_id`, so `/check` shows View Proof instead of an empty slot. Behavior changes: auto-ban records now carry the warn proof.

- **Founder gates read fresh role state** (`tcbot/database/users_roles.py`, `tcbot/modules/admins.py`, `tcbot/modules/stats.py`): promotion approve and reject buttons plus the founder-only users list now read the owner and effective role directly instead of the cached values, so a transfer in another process takes effect at once. Behavior changes: a transferred founder loses approve, reject, and list access immediately rather than after the cache window.

- **Role prompts name their opener for the action buttons** (`tcbot/modules/helper/keyboards/admin.py`, `tcbot/modules/admins/`, `i18n/en-US/admins.toml`, `i18n/id-ID/admins.toml`): the promote role buttons and the demote confirm button carry the staff member who opened the prompt, so a different staffer tapping gets an alert and the prompt stays live. Keyboard shapes for in-flight prompts keep working. Behavior changes: cross-staff taps on a pending role prompt alert instead of acting.

- **Warn family refuses verified bot targets** (`tcbot/modules/warns.py`, `tcbot/modules/mute.py`): warn, unwarn, resetwarns, and unmute verify the target is a bot before classifying, so the bot-target refusal actually fires. Ban, kick, and mute keep allowing bots, matching their refusal tables. Behavior changes: warning a proven bot now asks for a human target instead of warning the bot.

- **Main-group appeals in place** (`tcbot/modules/appeals.py`, `appeal_submit_flow.py`): a `#appeal` message in the main group submits through the same gates and posting as the DM deep link, including dual review cards. Behavior changes: `#appeal` in the main group opens an appeal for the sender's active ban.

- **Review cards post in both surfaces** (`appeal_submit_flow.py`): the staff review card with Approve/Reject buttons now lands in the main group and as a copy in the appeals destination, next to the forwarded appeal text. Behavior changes: staff can decide from either surface; the main-group card stays canonical for the stored review slot.

- **Proof upload splits large galleries at the Telegram limit** (`tcbot/modules/helper/pipelines/proof_flow.py`): albums longer than 10 items now send as successive media groups instead of being rejected as one oversized send. Behavior changes: large proof albums now land instead of producing a proof-less ban.

- **Error reports keep their traceback** (`tcbot/utils/logger.py`): the Telegram error handler ships a snapshot of the log record so clearing the live record after delivery no longer erases the traceback before the report runs. Behavior changes: error channel reports show the real exception and trace instead of an unknown-error label.

- **Staff roster resolves names live on cache miss** (`tcbot/modules/helper/pipelines/stats_flow.py`, `tcbot/modules/stats.py`): staff without a member-cache row now resolve through live identity (bounded, failures keep the numeric ID) instead of rendering the ID placeholder. Behavior changes: legacy staff rows show Telegram names in the roster.

- **Speedtest probes servers concurrently** (`tcbot/modules/netspeed.py`): best-server latency probes now run in parallel instead of one server after another. Behavior changes: server selection is faster on far routes; results keep the same fields.

### Changed

- **One owner for the role sets** (`tcbot/database/users_roles.py`): `STAFF_ROLES` and `FOUNDER_ADMIN_ROLES` replace eleven inline role-set literals across the moderation paths, so a new tier cannot land in the rank table and be missed by every set check. Behavior changes: none.

- **The error reporter is an application service** (`tcbot/error_reporter.py`, `tcbot/utils/logger.py`): the reporter moved from the utils layer to the package root, and it registers its shipping sink with the logger instead of the logger importing it. The utils layer no longer depends on the layer above it. Behavior changes: none; error reports still reach the same channel.

- **The hot path has a measured baseline** (`scripts/benchmark_hotpath.py`, `docs/operations/performance.md`): the database call transport, the two-level cache, and the bounded fan-out can now be measured in-process, without MongoDB, Redis, or a Telegram connection. Behavior changes: none; the benchmark is a development tool.

- **One configuration model instead of an adapter layer** (`tcbot/__init__.py`): the runtime configuration was parsed into one model and then forwarded property by property through a second class. Behavior changes: none; the same values are available under the same names, the list settings are immutable, and the model rejects mutation after loading.

- **The warn entry handler is named `cmd_warn`** (`tcbot/modules/warns.py`, `docs/architecture/modules.md`): the handler name matched its role in the flow rather than the command it serves. Behavior changes: none; the command, aliases, and replies are unchanged.

- **Local artifacts stay out of version control** (`.gitignore`): coverage data, pytest and hypothesis caches, HTML reports, and the proof-migration resume state are ignored, so local runs never leak into commits. Behavior changes: none for operators.
- **Manifest realigned to grouped dependency sets** (`pyproject.toml`, `uv.lock`): runtime, optional, and development dependencies are organised by responsibility; the test lint ignores narrow to the specific doc rules tests actually skip, and coverage is wired into the test workflow. Behavior changes: none for operators.

- **Database layer moves from Motor to synchronous PyMongo** (`tcbot/database/mongos.py`, `tcbot/database/*_db.py`, `tcbot/database/mtproto_store.py`, `tcbot/database/scheduler.py`, `scripts/migrate_proofs.py`): `db_call` now runs a zero-argument sync operation on a worker thread through the same MongoDB circuit; collections, indexes, schemas, and helper signatures are unchanged. A cancelled operation may still land once its thread finishes, which the atomic read patterns already tolerate. Behavior changes: none for operators.

- **Speedtest drops its heavy provider dependency** (`tcbot/modules/netspeed.py`, `tests/test_netspeed.py`, `pyproject.toml`): `/speedtest` now measures latency, download, and upload against speedtest.net over the certifi TLS bundle, rendering the same result fields; unavailable geodata shows "N/A". The share image is gone. Behavior changes: results no longer carry a share image.

- **Proofs default to the community proof channel** (`tcbot/__init__.py`, `config.env.example`, `docs/getting-started/setup.md`): an empty `PROOFS` now resolves to `-1003997518221` instead of compiling to no destination. Behavior changes: proof uploads have a destination on a fresh setup.

- **Greeting resolves the chat locale once per batch** (`tcbot/modules/greeting.py`): `on_new_member` resolves the group locale once and passes it down instead of resolving it per member. Behavior changes: none; batch joins make fewer reads.

- **Ban executor reads target locale and active ban in parallel** (`tcbot/modules/helper/pipelines/ban_flow.py`): the two independent reads now run in one gather instead of two sequential awaits. Behavior changes: none.

- **Warn counter migration runs concurrently** (`tcbot/database/warns_db.py`): per-user counter takes and merges now run through the bounded database gather helper instead of one user at a time. Behavior changes: none on the happy path; group upgrades with many legacy counters complete faster.

- **Display fallbacks now leave a debug trace** (`tcbot/modules/help.py`, `tcbot/modules/helper/pipelines/ban_flow.py`, `tcbot/modules/helper/pipelines/check_flow.py`): the help-entry, old-admin-name, and group-title fallbacks log at debug level instead of dropping failures silently. Behavior changes: none; user-facing text is unchanged.

- **Logging dependency carries an upper bound** (`pyproject.toml`, `uv.lock`): `loguru` now carries a `<1` bound like every other runtime dependency, so a future major cannot enter the lock silently. Behavior changes: none; the resolved version is unchanged.

- **Modules renamed and flattened to single files** (`tcbot/modules/`): `banning.py` becomes `bans.py`, `broadcasting.py` becomes `broadcast.py`, `connecting.py` becomes `connect.py`, `kicking.py` becomes `kick.py`, `muting.py` becomes `mute.py`, and `unbanning.py` becomes `unban.py`. The `admins/`, `checking/`, `greeting/`, `help/`, `maintenance/`, `stats/`, `syncing/`, and `warnings/` packages become `admins.py`, `check.py`, `greeting.py`, `help.py`, `maintenance.py`, `stats.py`, `sync.py`, and `warns.py`. Behavior changes: `MODULES_LOAD`/`MODULES_NO_LOAD` now take the new names (`bans`, `broadcast`, `check`, `connect`, `kick`, `mute`, `sync`, `unban`, `warns`), and in-flight help keyboards using old topic keys (`help_banning` and friends) stop working after upgrade.

- **`admins.py` is the command entry; executors live in flows** (`tcbot/modules/admins.py`, `tcbot/modules/helper/pipelines/promo_decision_flow.py`, `tcbot/modules/helper/pipelines/transfer_flow.py`): promote, demote, transfer, and queue commands plus their callbacks register from one file, while the promotion decision and ownership-transfer executors run from dedicated flow modules.

- **Resolve helpers shared by promote and demote live in decorators** (`tcbot/modules/helper/decorators/checks.py`): `resolve_executor_target`, `classify_and_load_role`, `check_callback_staff`, `prompt_owner_mismatch`, `cancel_owner_mismatch`, `action_owner_mismatch`, and `can_demote_admin` replace the old `admins/shared.py` copies.

- **`__all__` removed from every module under `tcbot/modules/`** (`tcbot/modules/`, `pyproject.toml`): package initializers stay re-export surfaces without export lists; new-file imports no longer need an export manifest. Behavior changes: none.

- **Message helpers split into safe edits and audit logs** (`tcbot/modules/helper/messages/`): the audit-log builders move to `audit_logs.py` and the safe-edit transport to `safe_edits.py` behind the same package import surface. Behavior changes: none.

- **Single-group enforcement calls are time-bounded** (`tcbot/modules/greeting/joins.py`, `tcbot/modules/greeting/requests.py`, `tcbot/modules/helper/pipelines/kick_flow.py`, `tcbot/modules/syncing/core.py`): join, join-request, kick, and sync enforcement writes now share the 3-second Telegram lookup budget instead of holding a join or fan-out slot until the HTTP timeout. Behavior changes: stalled calls now fail fast and retry on the next event instead of blocking.

- **Sync staff stripping runs concurrently** (`tcbot/modules/syncing/__init__.py`): role removals for banned/muted holders now run through the bounded gather helper instead of one await per holder. Behavior changes: none; same removals, less sequential latency.

- **Localized fallbacks for bot name and admin name** (`tcbot/modules/privacy.py`, `tcbot/modules/check.py`, `i18n/`): the privacy bot-name fallback and the checkme admin-name fallback read `privacy.msg.bot_fallback` and `checking.profile.admin_fallback` in the viewer's locale. Behavior changes: Indonesian viewers read translated fallback names; default-locale wording is unchanged.

- **Shared document types now type their writers** (`tcbot/database/users_roles.py`, `tcbot/database/settings_db.py`, `tcbot/database/users_roles.py`): `set_role` and `set_user_locale` write through `RoleDoc` and `UserSettingsDoc`, and `VALID_ROLES` is a literal tuple so the validation narrows the role. Behavior changes: none.

- **Unused helpers removed** (`tcbot/utils/circuit_breaker.py`, `tcbot/utils/i18n.py`, `tcbot/utils/prefixes.py`): `is_open`, `reload_catalog`, and `_BotLike` had no callers. Behavior changes: none.

- **App lifecycle lives in one file** (`tcbot/__main__.py`, `tcbot/serverless.py`, `tests/test_runtime_errors.py`, `tests/test_reliability_regressions.py`, `AGENTS.md`, `docs/architecture/repository-map.md`, `docs/architecture/database.md`, `docs/operations/performance.md`, `docs/operations/vercel.md`): builder, lifecycle, errors, member cache, and entry merge into the process entry point. Behavior changes: none.

- **Error reporting lives in one file** (`tcbot/utils/error_reporter.py`, `tests/test_error_reporter_classify.py`, `AGENTS.md`, `docs/architecture/repository-map.md`, `docs/architecture/utilities.md`, `docs/operations/ci-cd.md`): classify, format, state, and ship merge into one module. Behavior changes: none.

- **Config lives in one file** (`tcbot/__init__.py`, `tcbot/modules/helper/pipelines/appeal_submit_flow.py`, `tests/test_wave_regressions.py`, `AGENTS.md`, `docs/architecture/repository-map.md`, `docs/getting-started/setup.md`): env parsing, the Configs model, and the cfg adapter merge into the top package. Behavior changes: none.

- **Failed bot checks and error filters leave a trace** (`tcbot/modules/helper/identity.py`, `tcbot/__main__.py`, `tests/test_identity_copy.py`, `tests/test_runtime_errors.py`): the Telegram membership probe behind bot verification and the benign-error filter behind the global error handler now log their own failures at debug level instead of dropping them silently. Verification still defers to MTProto and errors still ship as reports. Behavior changes: none; degraded lookups are visible in logs.

- **Additional Links shows all five buttons by default** (`tcbot/__init__.py`, `config.env.example`, `docs/getting-started/setup.md`): Discussion Group and Appeals Channel gain built-in links, so a fresh setup shows Main Channel, Discussion Group, Logs Channel, Appeals Channel, and TRAVEL without manual values. Behavior changes: the two buttons now appear even when their env vars are empty.

- **Appeal submission lives in one module** (`tcbot/modules/helper/pipelines/appeal_submit_flow.py`): review posting, the handler factory, and instruction text each have one section in a single file. Retry behavior is unchanged.

- **24/7 runner re-enabled** (`.github/workflows/run-bot.yml`, `README.md`, `docs/operations/ci-cd.md`, `.agents/rules/docs-sync.md`, `AGENTS.md`, `docs/architecture/helpers.md`): the self-chaining runner moves from `.github/workflows.disabled/` back to `.github/workflows/` and schedules again with push-triggered handover and cron fallback. Behavior changes: the bot auto-runs via GitHub Actions again; repository secrets still need to be set once.

- **Role and group helpers live in focused packages** (`tcbot/database/users_roles.py`, `tcbot/database/groups_db.py`, `tcbot/modules/helper/pipelines/promote_flow.py`): owner, admin, custom-role, and resolution logic; core, pending, migration, and locale group logic; and assign, request, and alias promotion logic each have one home with a thin re-exporting package. Dotted import paths, callback data, and handler registration are unchanged. Behavior changes: none.

- **Scheduler sync runs through an injected runner** (`tcbot/database/scheduler/`, `tcbot/__main__.py`): the database package never imports a command module; startup injects the enforcement runner after the scheduler starts. Behavior changes: none; scheduled sweeps run as before without the import cycle.

- **Fan-out failure summaries share one helper** (`tcbot/utils/dispatch.py`, `tcbot/modules/helper/pipelines/ban_flow.py`, `tcbot/modules/helper/pipelines/mute_flow.py`, `tcbot/modules/helper/pipelines/unban_flow.py`, `tcbot/modules/helper/pipelines/appeal_review_flow.py`): the error-level transient summary is emitted from one place while per-group warnings and applied lines stay per-flow. Operator-facing counts are unchanged. Behavior changes: none, consistent partial-failure reporting.

- **Self-check callbacks share one ban loader** (`tcbot/modules/check.py`): callback parsing and the parallel answer-plus-fetch live once so the detail and back paths cannot drift. Behavior changes: none.

- **Python floor and codec bound match the deployed runtime** (`pyproject.toml`, `uv.lock`, `AGENTS.md`, `replit.md`, `docs/getting-started/setup.md`): the floor is now 3.14 (the tested runtime) and the structured-codec version carries an upper bound. Behavior changes: none; installs on older runtimes now fail fast.

- **Docker port follows the environment** (`Dockerfile`, `docker-compose.yml`): the published port and health probe use the configured port instead of a fixed 5000. Behavior changes: custom ports work in Docker.

- **Moderation requires a federation origin** (`tcbot/modules/banning.py`, `tcbot/modules/mute.py`, `tcbot/modules/kicking.py`, `tcbot/modules/warns.py`, `tcbot/modules/unbanning.py`, `tcbot/modules/syncing/command.py`): ban, unban, and sync accept bot DM or any connected or primary group, while mute, warn, kick, and their manage commands require a connected or primary group. A connection-state outage blocks the action with a retry notice instead of proceeding. Behavior changes: commands from disconnected groups, and private mute, warn, and kick, are refused.

- **Ownership transfer needs a verified human** (`tcbot/modules/admins/transfer.py`, `tcbot/modules/helper/identity.py`): transfer proceeds only when the target is verified human. A verified bot is refused, and an indeterminate lookup asks for a retry instead of granting ownership on the benefit of the doubt. Promotion keeps allowing unknown off-group targets. Behavior changes: transfer during a lookup outage asks for a retry.

- **Telegram circuit trips on accumulated transients** (`tcbot/utils/circuit_breaker.py`, `tcbot/utils/dispatch.py`): ordinary successes no longer erase earlier transient failures, so a partial outage with interleaved successes can still open the circuit and skip doomed slots. Only a successful recovery probe closes it. Behavior changes: partial outages pause quickly instead of firing timeouts.

- **Catalog loads at startup on both transports** (`tcbot/__main__.py`, `tcbot/serverless.py`): the message catalog loads once during startup rather than on the first command, so the first reply no longer pays the full file scan on the event loop. Behavior changes: none visible, faster first reply.

- **Index startup stays inside the connection pool** (`tcbot/database/mongos/indexes.py`): every index creation runs through the database circuit and the startup batch runs with bounded concurrency instead of firing all at once. Behavior changes: none on healthy startup.

- **Member harvest batches its writes** (`tcbot/database/mtproto/harvest.py`): group backfill collects identities and flushes them in bounded batches instead of awaiting one write at a time, while the time budget, flood handling, and partial counts stay the same. Behavior changes: none, faster backfill.

- **Safe edits share one failure policy** (`tcbot/modules/helper/parse_editmsg.py`): the three message-edit helpers delegate to one internal runner with the same benign-error, logging-level, and catch-all behavior. Log output and swallowed errors are unchanged. Behavior changes: none.

- **One owner for every safe edit** (`tcbot/modules/helper/parse_editmsg.py`, fourteen modules under `tcbot/modules/`): `safe_edit`, `safe_edit_cb`, and the new `safe_edit_message` accept a log level, call-site label, and catch-all option, and the duplicated inline edit-error handlers across the admin, check, stats, start, language, netspeed, ban, mute, and appeal paths delegate to them with identical log output. Behavior changes: none to user-visible output; benign not-modified edits are now dropped silently instead of logging a debug line, matching every other safe-edit site.

- **Group-permission check lives in one helper** (`tcbot/modules/helper/identity.py`, `tcbot/modules/language.py`, `tcbot/modules/disconnecting.py`): the language and disconnect commands share `can_manage_group`. Behavior changes: staff are no longer refused `/tcdisconnect` when the group-membership probe fails (their authority already covers force-remove via `/rmtc`); non-staff still need the creator probe to pass and get the standard not-authorized refusal on failure.

- **Rate-limit windows owned by their packages** (`tcbot/modules/checking/`, `tcbot/modules/stats/`): the shared limits live in each package init instead of crossing submodules as private constants. Behavior changes: none.

- **Dead fan-out counting helper removed** (`tcbot/utils/dispatch.py`, `tcbot/modules/helper/pipelines/connected_flow.py`): failure counts use the benign-aware counter only. Behavior changes: none.

- **Transports share one application builder and Redis decision** (`tcbot/serverless.py`, `tcbot/__main__.py`, `tcbot/database/redis_client.py`): the PTB builder chain lives once in the process entry point, the Redis connect/degrade decision lives once in the redis client, and serverless imports handlers from the entry module. Behavior changes: none.

- **Chat-migration repoint in one helper** (`tcbot/database/_migration.py`, `kicks_db.py`, `mutes_db.py`, `warns_db/migrate.py`): kick, mute, and warn history repoint through one shared helper. Behavior changes: none; repoint-failure log lines now carry the shared helper's logger tag.

- **Dependency versions bumped to latest releases** (`pyproject.toml`, `uv.lock`): lower bounds and pinned versions now track the current releases of every runtime and development dependency, including Motor, Flask, Redis, cachetools, Kurigram, loguru, msgspec, and the testing and lint tooling. Behavior changes: none.

- **Oversized modules split into packages, every file at most 1000 lines** (`tcbot/modules/admins/`, `checking/`, `stats/`, `help/`, `maintenance/`, `warnings/`, `syncing/`, `greeting/`, `helper/keyboards/`, `helper/parse_logmsg/`, `helper/decorators/`, `helper/extraction/`, `database/cache/`, `scheduler/`, `warns_db/`, `bans_db/`, `users_cache/`, `mongos/`, `mtproto/`, `mtproto_store/`; `tcbot/modules/__init__.py` now also discovers packages): each former giant becomes focused submodules plus a thin `__init__.py` re-exporting the public surface, so callback data, messages, and handler registration are unchanged. Mixin typing across the new packages is explicit (shared bases, member stubs, no invalid `self` annotations). Behavior changes: none; the full suite passes identically. The 1000-line budget is now a code-style rule (`.agents/rules/code-style.md`) enforced by a CI step in the Ruff workflow.

- **One home for every inline keyboard** (`tcbot/modules/helper/keyboards.py`, `reason_flow.py`, `proof_flow.py`, `connected_flow.py`, `stats_flow.py`, `check_flow.py`, `tcbot/utils/pagination.py`): step keyboards, stats/check lists, profile dashboard, and warn-group lists are defined once in the keyboard module, and the flow classes keep thin delegating steps so call sites and callback data are unchanged. In-flight keyboards keep working.

- **Help index follows the tapper's locale** (`tcbot/modules/help.py`): topic lists, the `/help <module>` name map, and the prefix footer rebuild per request instead of serving the import-time default-locale snapshot. Behavior changes: Indonesian tappers now read translated index content and can look up modules by Indonesian name.

- **Warn clears repair stale counters and migration merges them** (`tcbot/database/warns_db.py`): a failed counter delete now recounts the pair (single-group clear) or retries the delete (federation-wide clear) instead of leaving counts a later warn would increment from. Group migration sums per-user counters into the new chat instead of overwriting one side. Behavior changes: clears never leave stale auto-ban counts behind.

- **Unknown stored roles grant nothing** (`tcbot/database/users_roles.py`): resolution ignores a `tc_roles` value outside the accepted custom set (logged as an error, treated as no custom role) instead of returning it verbatim. Behavior changes: a legacy or hand-edited row naming a privileged role no longer confers that role.

- **Shutdown cancels cleanly instead of deciding dirty** (`tcbot/modules/greeting.py`, `warn_flow.py`, `ban_flow.py`, `mute_flow.py`, `maintenance.py`, `appeal_submit_flow.py`, `tcbot/__main__.py`, `tcbot/utils/dispatch.py`, `tcbot/utils/logger.py`, `connected_flow.py`): every enforcement and migration read propagates cancellation before acting, background sets drain bounded at teardown, and the appeal cancel ignores stale prompts. Behavior changes: shutdowns no longer greet, enforce, or migrate; in-flight shutdown work stops instead of logging as data failure.

- **Warn migration cannot double-count on retry** (`tcbot/database/warns_db.py`): each old counter is consumed with an atomic take before its count lands on the new pair, so a crash plus retry can only under-count, never trigger a false auto-ban. Counter-delete repair retries bounded with backoff. Behavior changes: none on the happy path.

- **Ownership transfer cannot leave zero owners** (`tcbot/database/users_roles.py`, `tcbot/modules/admins.py`): the owner row lands in one upsert write with a converging cleanup, and owner reads sort deterministically. Behavior changes: none on the happy path; a mid-flight crash keeps the new owner instead of risking an empty table.

- **Enforcement taps re-check rank** (`tcbot/modules/helper/decorators.py`, `reason_flow.py`, `ban_flow.py`): Done, Skip, and re-ban Continue verify the tapper still meets the entry rank, so a mid-window demotion cannot enforce from a stale prompt. Behavior changes: demoted tappers get a refusal reply and the flow ends.

- **Warn auto-ban records before it announces** (`tcbot/modules/helper/pipelines/warn_flow.py`): the federation record is created first and the audit card follows with its id attached, so a failed write can no longer leave a phantom card. Behavior changes: the log card appears after the record instead of before.

- **Checks page newest-first from the server** (`tcbot/database/warns_db.py`, `check_flow.py`): per-chat warn drill-downs fetch the newest slice directly instead of reversing an oldest-first page. Behavior changes: page one shows the newest warns on long histories.

- **Connect reports blind replays honestly** (`tcbot/modules/connecting.py`, `connected_flow.py`): the owner prompt shows the blind warning (and the failure card on error) instead of confirming success, and huge replays truncate into the same warning with `/tcsync` closing the gap. Behavior changes: outage connects show the warning, not success text.

- **Stats views degrade honestly and stay on their card** (`tcbot/modules/stats.py`, `stats_flow.py`, `keyboards.py`): overview totals carry an incomplete note on partial outage, lists render a retry card instead of empty, search input is accepted only from the panel chat, and search detail verifies the stable record id. Behavior changes: outage views differ from empty ones; cross-chat input is ignored.

- **Kick/mute history survives group migration** (`tcbot/database/kicks_db.py`, `mutes_db.py`, `groups_db.py`, `tcbot/modules/greeting.py`): kick and mute rows repoint alongside warns, and group migration merges into an existing target row instead of dying on the unique index. Behavior changes: `/check` histories stay whole after upgrades.

- **Single merge for primary groups** (`tcbot/database/groups_db.py`, five workflow call sites): every fan-out builds its connected-plus-primaries list through one helper. Behavior changes: none, same chats covered.

- **Prefix-wide cache clears are never dropped** (`tcbot/database/cache.py`): the mutation-queue bound skips revocations, and the clear wait is bounded so a dead backlog delays briefly instead of stalling. Behavior changes: revocations always reach Redis.

- **MTProto store indexed and fresh** (`tcbot/database/mtproto_store.py`, `mongos.py`): username/phone lookups gain indexes, namespace patterns are escaped, and username writes bump the freshness timestamp the expiry check reads. Behavior changes: lookups stay fast as membership grows; refreshed names stop expiring early.

- **Scheduler store client fully bounded** (`tcbot/database/mongos.py`, `scheduler.py`): the job-store connection shares the socket and pool bounds. Behavior changes: none on healthy runs.

- **Health treats both circuits the same** (`tcbot/alive.py`): a half-open Telegram circuit degrades the verdict like MongoDB already did; Redis stays a hint-only field. Behavior changes: recovery probes report degraded instead of ok.

- **Independent reads run in parallel on promotion and appeal paths** (`tcbot/modules/admins.py`, `appeal_review_flow.py`): the promotion-list slice and its total, plus the review-card and DM locales on approve, reject, and appeal-reject, load in one gather instead of two serial round trips. Behavior changes: none, same replies with fewer sequential waits.

- **Cleanup database burst stays bounded without the Telegram breaker** (`tcbot/utils/dispatch.py`, `tcbot/modules/maintenance.py`): bulk deactivations run through a new bounded gather helper that keeps the concurrency cap and cancellation contract but never reads or trips the Telegram circuit. Behavior changes: none on the happy path; large cleanups no longer spike the database pool.

- **Redis payloads encode via msgspec** (`tcbot/database/cache.py`, `pyproject.toml`, `uv.lock`, `docs/architecture/database.md`): the L2 tagged-JSON codec moves from stdlib `json` to msgspec with the identical wire shape (datetimes and ObjectIds are pre-tagged in Python because msgspec natively flattens datetimes to bare strings). Legacy payloads decode to the same runtime types, verified by an old-vs-new round-trip check. Behavior changes: none, same values with less encode overhead.

- **Health and webhook JSON paths run on msgspec** (`tcbot/alive.py`, `api/webhook.py`): the `/health` body renders from a typed msgspec struct with the same keys in the same order, and the Vercel webhook decodes the Telegram update with msgspec (one `DecodeError` clause replaces the `JSONDecodeError` plus `UnicodeDecodeError` pair with the same 400 outcome). Update dicts decode identically, verified against nested unicode payloads. Behavior changes: none.

- **Loguru adopted with per-update tracing context** (`tcbot/utils/logger.py`, `tcbot/modules/helper/decorators.py`, every module logger, `tests/conftest.py`): all module loggers run through loguru into the same colored handlers, bridged to stdlib so capture and error shipping keep working, and `log_execution` binds `update_id`/`user_id`/`chat_id` rendered on every line until cleared. Import-time loggers stay on stdlib since they emit before setup. Behavior changes: log lines carry a request-context segment.

- **Small latency trims on mute, appeal-approve, and transport** (`tcbot/modules/helper/pipelines/mute_flow.py`, `appeal_review_flow.py`, `tcbot/utils/transport.py`, `docs/operations/performance.md`): the mute executor resolves its locale once instead of twice, appeal-approve resolves both locales up front in parallel instead of inline during fan-out setup, and the Telegram HTTP pool grows 8 to 16 so one full fan-out plus concurrent traffic never queues on pool exhaustion. Behavior changes: none.

- **Module docstrings normalized to one line** (twelve modules under `tcbot/database/`, `tcbot/utils/`, and `tcbot/modules/helper/`): summaries stay on the first line per project style; the two contracts with no other home moved instead of deleted (formatter escaping rules stay with the escape tables, MTProto storage layout and semantics stay with the key helpers and class). Behavior changes: none, comments only.

- **Tests for the new dispatcher, codec, and logging helpers** (`tests/test_dispatch.py`, `tests/test_cache_codec.py`, `tests/test_logger_context.py`): the suite grows from 313 to 324 checks covering bounded-concurrency caps and cancellation, codec round-trips plus legacy payloads, and context rendering plus log routing. Behavior changes: none.

- **Comment cleanup across handlers and runtime** (`tcbot/__main__.py`, `tcbot/alive.py`, `tcbot/modules/help.py`, `privacy.py`, `about.py`, `start.py`, `stats.py`, `checking.py`, `muting.py`): removed a dozen restatements of adjacent code (parallelism notes duplicated from helper docstrings, header lines duplicated from function docstrings, branch labels) and compressed two notes to their rationale. Security, ordering, and failure-semantics notes stay untouched. Behavior changes: none, comments only.

- **Dependency lockfile refreshed to latest allowed versions** (`uv.lock`): `cachetools` 7.1.8 to 7.2.0, `ruff` 0.16.7 to 0.16.8, plus transitive `idna` 3.19 to 3.20 and `virtualenv` 21.7.10 to 21.7.11 via `uv lock --upgrade`. Every other pin was already latest in range, and `apscheduler` stays at the deliberate `3.11.3` pin. Full suite passes identically on the new lockfile. Behavior changes: none.

- **Test stack moves to pytest 9** (`pyproject.toml`, `uv.lock`): `pytest` 8.4.2 to 9.1.1 plus `pytest-asyncio` 0.26.0 to 1.4.0, closing the medium tmpdir-handling advisory that pinned the old line (the async plugin capped `pytest<9`). The suite uses no async test functions, so the major bump changes nothing observable. Behavior changes: none.

- **Auto-fix runs the suite in parallel** (`.github/workflows/auto-fix.yml`, `docs/operations/ci-cd.md`): the capture and summary steps use `-n auto` like the main test workflow. Behavior changes: none, faster feedback only.

- **Fatal startup banner prints in red** (`tcbot/__main__.py`): the pre-logging stderr banner uses the error red unconditionally, matching the always-colored console formatter. Behavior changes: none, same text.

- **Harvest backfill comment reworded** (`tcbot/database/mtproto.py`): the sequential-scan note reads as plain English. Behavior changes: none, comments only.

- **Fatal traceback prints in red with test cover** (`tcbot/__main__.py`, `tests/test_fatal_output.py`): the startup traceback renders through the banner color so every fatal line is red, pinned by a stderr-capture test. Behavior changes: none, same text.

- **Undecodable Vercel updates answer 400, not 500** (`tcbot/serverless.py`): a payload that fails `de_json` can never parse on retry, so it is rejected like any other malformed body instead of inviting pointless Telegram retries. Matches the documented response contract. Behavior changes: decode failures return `400` instead of `500`.

- **Sync pair selection never materializes the cross product** (`tcbot/modules/syncing.py`): `take_pairs` takes from a lazy generator via `islice` instead of building the full user-by-group list before truncating, so a huge federation sweep no longer spikes memory and CPU to discard almost all of it. Same pairs, same truncation flag. Behavior changes: none.

- **One owner for conversation state keys and list rendering** (`tcbot/modules/helper/pipelines/ban_flow.py`, `banning.py`, `kicking.py`, `muting.py`, `warnings.py`, `groups.py`, `start.py`, `tests/test_ban_flush_cleanup.py`): the ban key tuple lives once in `ban_flow` as `BAN_USER_DATA_KEYS` (the parallel entry-point list is gone, including a `ban_duration` entry nothing ever set), kick/mute/warn key tuples move to module level with the mute prompt ID completed, and the shared group-list renderer is public as `render_groups` instead of a cross-module private import. Behavior changes: none.

- **Promotion and ownership transfer refuse verified bot targets** (`tcbot/modules/admins.py`, `tcbot/modules/helper/identity.py`, `i18n/en-US/admins.toml`, `i18n/id-ID/admins.toml`): a shared verified-only check (quoted sender, one bounded membership probe, one MTProto peer lookup) refuses bot targets, while unknown targets stay allowed so off-group promotions keep working. Behavior changes: promoting a proven bot, or transferring ownership to one, now replies with a refusal instead of granting privilege.

- **Demote clears both role collections** (`tcbot/modules/helper/pipelines/demote_flow.py`): the removal step clears the admin row and the custom-role row together and reports success when either was present. Behavior changes: a stale row in the other collection can no longer resurrect privilege on a later demote.

- **Unwarn fails closed on write outage** (`tcbot/database/warns_db.py`, `tcbot/modules/helper/pipelines/warn_flow.py`, `docs/features/moderation/warnings.md`): a failed warning delete raises instead of reporting success state, and the command replies with the database-retry notice. Behavior changes: an outage during unwarn says the database is unreachable instead of claiming the user has no warnings.

- **Ban summary falls back to a fresh reply** (`tcbot/modules/helper/pipelines/ban_flow.py`): when the prompt message cannot be edited, the outcome is sent as a new message like the kick and mute executors already do. Behavior changes: moderators always see the ban outcome even when the prompt was deleted.

- **Re-ban confirmation reuses the resolved locale** (`tcbot/modules/banning.py`, `tcbot/modules/admins.py`): entry commands pass their locale into the confirmation and target-resolution helpers. Behavior changes: none, the same reply with two fewer database reads per command.

- **Every callback tap answers the spinner first** (`tcbot/modules/checking.py`, `tcbot/modules/admins.py`, `tcbot/modules/helper/pipelines/connected_flow.py`): handlers with missing callback data acknowledge the query before returning instead of leaving the client spinner hanging. Behavior changes: malformed taps dismiss the spinner instead of timing out.

- **Remaining hardcoded English strings move to the catalog** (`tcbot/modules/connecting.py`, `stats.py`, `admins.py`, `checking.py`, `i18n/en-US/connecting.toml`, `stats.toml`, `admins.toml`, `checking.toml`, `i18n/id-ID/*`): help section titles and the unknown-date word render in the viewer's locale. Behavior changes: Indonesian viewers read translated titles where English leaked through; default-locale wording is unchanged.

- **Mention batch reads share one implementation** (`tcbot/database/users_cache.py`): both batch readers funnel through a single triple-fetching helper, so miss handling and sentinel caching cannot drift between them. Behavior changes: none, same values with one code path.

- **User-list sorts limited to indexed fields** (`tcbot/database/users_cache.py`): unindexed sort keys fall back to first-name order instead of forcing a collection scan plus an in-memory sort. Behavior changes: requests for removed sort keys render in first-name order.

- **Sync sweep order is deterministic** (`tcbot/modules/syncing.py`, `docs/features/moderation/sync.md`): group and ban ID lists are sorted before pairing, so the checked order and the truncation victims are identical run to run. Behavior changes: repeated truncated sweeps converge instead of covering arbitrary slices.

- **Webhook decode failures answer 400, enqueue failures 500** (`tcbot/alive.py`): undecodable bodies are rejected before the enqueue path, and the catch-all message names enqueueing only. Behavior changes: malformed webhook bodies return `400` instead of `500`; transient queue failures still return `503`/`500`.

- **Health reports the update-queue depth** (`tcbot/alive.py`, `docs/operations/backup-and-restore.md`): the `/health` body gains an `update_queue` field showing PTB backlog (`null` before the receiver is wired). Behavior changes: one new response field for watchdog paging; the verdict logic is unchanged.

- **Shutdown closes the shared MongoDB client** (`tcbot/database/mongos.py`, `tcbot/__main__.py`): the connection handle is retained at connect time and closed after every drain at teardown. Behavior changes: none on the happy path; pooled sockets release instead of lingering past shutdown.

- **MTProto resolvers share one peer lookup** (`tcbot/database/mtproto.py`): name resolution and the bot-flag check funnel through a single fetch helper with identical flood handling, so the two can no longer disagree on failure semantics. Behavior changes: a flood wait during a bot-flag check now logs a warning like name resolution does.

- **Member harvest stops on a time budget** (`tcbot/database/mtproto.py`): the backfill scan returns its count so far after 25 seconds instead of running unbounded. Behavior changes: huge harvests yield a partial count with a warning instead of stalling moderation traffic.

- **Error reports redact exact configured secrets** (`tcbot/utils/error_reporter.py`): the scrubber replaces the configured token, URIs, hashes, and secrets verbatim before the existing pattern redaction runs. Behavior changes: none on the happy path; a report echoing a value verbatim shows a marker instead of the value.

- **Module lists accept literal lists or CSV** (`tcbot/__init__.py`): the allowlist and denylist readers share the same parser as command prefixes. Behavior changes: none, comma-separated values work exactly as before.

- **Plain-HTTP webhook URLs warn at startup** (`tcbot/__init__.py`): an explicit non-localhost `http://` webhook URL logs a warning that Telegram requires HTTPS. Behavior changes: warning log only, registration still attempted.

- **Environment file loads once at config load** (`tcbot/__init__.py`): the import-time dotenv call is gone; loading happens inside config construction. Behavior changes: none, importing the package no longer touches the filesystem.

- **Prefix list returns a copy** (`tcbot/__init__.py`): callers receive a fresh list instead of the stored one. Behavior changes: none, accidental mutation can no longer corrupt command parsing.

- **Benign-match tables precomputed, circuit-open log summarized** (`tcbot/utils/dispatch.py`): the normalized refusal patterns build once at import, and an open-circuit fan-out logs one summary line with the skipped count instead of one line per slot. Behavior changes: quieter logs during circuit-open bursts; matching results are identical.

- **Cron endpoint rejects POST explicitly** (`api/cron.py`): non-GET callers get `405` with a warning line instead of the default `501` silence. Behavior changes: POST now answers `405`.

- **Both transports share one startup path** (`tcbot/__main__.py`, `tcbot/serverless.py`): the connect, index, owner-seed, Redis, and error-reporter steps live in one helper both transports call, so a change lands on webhook, polling, and serverless together. Serverless still skips MTProto as before. Behavior changes: none.

- **Scheduler receives its sync runner explicitly** (`tcbot/database/scheduler/`, `tcbot/__main__.py`): the enforcement runner is now a start argument instead of a private attribute patched after startup, so the scheduled sweep can never run before its runner exists. Behavior changes: none.

- **Check keyboards have one owner** (`tcbot/modules/helper/keyboards/check.py`, `check_flow.py`): the back and paged markups are built in the keyboard package, and the check flows keep only the text rendering. Button labels, callback data, and in-flight keyboards are unchanged. Behavior changes: none.

- **New group issuance reads live connection state** (`tcbot/modules/greeting/`, `connecting.py`, `disconnecting.py`, `language.py`, `connected_flow.py`): join enforcement, connect, disconnect, bot-added, join-decision, and group-language writes now read the connection row directly instead of the cached value, so a disconnect stops enforcement at once. Display reads keep the cached fast path. Behavior changes: a disconnect stops join enforcement immediately rather than after the cache window.

- **Speedtest patch degrades honestly** (`tcbot/modules/netspeed.py`): the certifi context patch now checks the handler actually carries the expected attribute and logs a warning otherwise, so an upstream layout change fails open with a trace instead of silently losing TLS intent. Behavior changes: none on the pinned release.

- **Top package exposes only the config surface** (`tcbot/__init__.py`, `tests/test_wave_regressions.py`): the package now exports `cfg`, `configs`, and `Configs` only; the parsing helpers stay in `tcbot/__init__.py`. Behavior changes: none.

- **Exec group removed entirely** (`tcbot/__init__.py`, `keyboards/menus.py`, `with_primary_groups` call sites, `i18n/`, `.github/workflows/run-bot.yml`, `config.env.example`): `EXTEND_GROUP` and the exec button are gone, so fan-outs and guards cover the main group only. Behavior changes: the exec group is now an ordinary group (previously it was always enforced and protected).

- **Community discussion and exec links lose their built-in defaults** (`tcbot/__init__.py`, `menus.py`, `config.env.example`): the discussion and exec buttons render only when set explicitly, with no preset URLs. Behavior changes: a fresh deployment no longer shows preset discussion/exec buttons.

- **Error reports fall back to the owner** (`tcbot/utils/error_reporter.py`): with no `LOGS_ERRORS` channel configured, reports ship to the owner DM instead of being dropped. Behavior changes: an empty `LOGS_ERRORS` now still reaches the operator.

- **Moderation flows live in one module each** (`tcbot/modules/helper/pipelines/`): the fragmented workflow subpackages are now single modules (`ban_flow.py`, `reason_flow.py`, `kick_flow.py`, `mute_flow.py`, `warn_flow.py`, and the appeal, check, stats, promote, demote, connected, proof, and unban flows), so the code a moderator action touches is easy to find and review. Behavior changes: none; import paths moved, callback data and handler registration are unchanged.

- **Mute duration parsing lives in one helper** (`tcbot/utils/time_and_date.py`, `tcbot/modules/mute.py`, `tcbot/modules/helper/pipelines/mute_flow.py`): duration parse and format live with the other time helpers, and the mute entry parses the token once instead of checking a pattern and then parsing again. Behavior changes: none; identical tokens, identical replies.

- **Flow modules carry section dividers and concise notes** (`tcbot/modules/helper/pipelines/`): each moderation flow now opens its executor, handler, and factory blocks with one divider line, and decision points that are not obvious from the code carry one short note. Behavior changes: none, comments only.

- **Chat destination parsing gains regression coverage** (`tests/test_wave_regressions.py`): plain, threaded, empty, and invalid chat values now have a regression check; the fallback to 0 is pinned. Behavior changes: none.

- **Benign refusal matching skips a dead comparison** (`tcbot/utils/dispatch.py`): the Telegram refusal check looks only at the normalized message, since the raw form can never match a stripped pattern on its own. Behavior changes: none; the same refusals are treated as benign.

- **Error shipments log through the module logger** (`tcbot/utils/error_reporter.py`): failed shipments to the log channel and the owner DM now use the same logger as the rest of the reporter instead of the root logger. Behavior changes: none; the message text is unchanged with a clearer module name.

- **Config and module discovery log via Loguru** (`tcbot/__init__.py`, `tcbot/modules/__init__.py`): the last two standard-library loggers now use the project logger, and the log-level parsing no longer reads the standard library. A small level table keeps the same fallback to INFO. Behavior changes: none; early warnings are now visible in the same format as later logs.

- **Utils submodules load on demand** (`tcbot/utils/__init__.py`): importing any single submodule no longer pulls the whole package, so the config entry can import the logger without a circular import. Behavior changes: none; import paths and handler delivery are unchanged.

- **Message helpers live in one package** (`tcbot/modules/helper/messages/`): safe edit and reply helpers plus the audit-log builders share one package (`safe_edits.py`, `audit_logs.py`). Behavior changes: none; import paths moved, message content and handler registration are unchanged.

- **File-size gate matches the documented budget** (`.github/workflows/lint-ruff.yml`): the size check now allows up to 1000 lines per file as the guides state. Behavior changes: none for operators; existing large flows are no longer a gate failure.

- **Utils package is a plain namespace** (`tcbot/utils/__init__.py`): the package initializer no longer carries a lazy `__getattr__` loader, since direct submodule imports already avoid pulling the whole package. Behavior changes: none; import paths and handler delivery are unchanged.

- **Locale resolution reads one row per message** (`tcbot/modules/helper/locale.py`, `docs/architecture/helpers.md`): private chats read only the user preference and group-like chats read only the group row, instead of reading both and discarding one. Behavior changes: none; replies render in the same locale with one fewer lookup per resolution.

- **Helper packages expose only the public API** (`tcbot/modules/helper/decorators/__init__.py`, `tcbot/modules/helper/extraction/__init__.py`, `tcbot/modules/helper/extraction/resolve.py`, `tcbot/modules/admins.py`): private helpers and the database re-export leave the package namespaces, and the shared reply-target decision is public as `reply_uid`. Behavior changes: none; handlers, callbacks, and database behavior are unchanged.

- **Logging never raises on format or timestamp failures** (`tcbot/utils/logger.py`, `tcbot/utils/time_and_date.py`): percent formatting and console timestamp conversion fall back to a degraded line instead of raising into the caller, and the duration helper imports the catalog at module level. Behavior changes: none on the happy path; malformed format strings and shutdown stamp failures render placeholders instead of crashing the handler.

- **Database helpers live in single files** (`tcbot/database/bans_db.py`, `tcbot/database/groups_db.py`, `tcbot/database/mongos.py`, `tcbot/database/mtproto.py`, `tcbot/database/mtproto_store.py`, `tcbot/database/scheduler.py`, `tcbot/database/users_cache.py`, `tcbot/database/users_roles.py`, `tcbot/database/warns_db.py`): every former `*_db/` and support package merges its submodules into one file, so each domain has one home. Behavior changes: none; `db.*` keeps the same functions and patchable globals, and scheduler job paths stay on `tcbot.database.scheduler`.

- **Dependency versions bumped to latest releases** (`pyproject.toml`, `uv.lock`): `cachetools` moves to 8.0.0 and `kurigram` to 2.2.27, with `kuricrypt` replacing `tgcrypto` and `virtualenv` to 21.15.6 via the lockfile. Behavior changes: none. The `apscheduler` pin stays at 3.11.3.

- **Sync runner imports at startup** (`tcbot/__main__.py`): the enforcement sync runner now imports at module level instead of inside startup, so the scheduler wiring follows the same top-level import rule as every other handler dependency. Behavior changes: none; scheduled sweeps run as before.

- **Join notices await directly** (`tcbot/modules/greeting.py`): the single banned-joiner notice now awaits its reply directly instead of gathering a zero-or-one item list, keeping the same debug log and cancellation propagation with one less indirection. Behavior changes: none; replies and logs are unchanged.

### Fixed

- **A name search no longer scans the whole member cache** (`tcbot/database/users_cache.py`, `tcbot/database/mongos.py`): the search matched a case-insensitive regex, and MongoDB cannot use an index for one, so every search scanned every member the bot had ever seen. The search now runs an indexed case-sensitive prefix query over lowercase mirror fields, and a startup backfill fills the mirrors for the rows older releases wrote. Behavior changes: none; the same names match.

- **An unchanged member profile is no longer rewritten on every message** (`tcbot/database/users_cache.py`): the profile write invalidated the mention cache instead of populating it, so the change-detection guard could never fire for a member who was never rendered anywhere. Every message from an ordinary member cost a database update and a queued cache delete for data that had not changed. Behavior changes: the write populates the cache, so an unchanged profile costs no database round trip after the first message.

- **Database calls get their own worker pool and a per-call budget** (`tcbot/database/mongos.py`): database work shared the event loop's default executor with other blocking calls, and a caller waited for the full socket timeout on a hung operation. Behavior changes: database calls run on a dedicated bounded pool, a hung operation releases the caller after 20 seconds, and the timeout counts as an outage signal for the circuit breaker.

- **A Redis outage no longer disables the shared cache for the process lifetime** (`tcbot/database/redis_client.py`, `tcbot/database/cache/`): a Redis that was down at boot was never re-established, so cross-process role and connection state diverged until the key TTL expired. Behavior changes: the client is re-established lazily, at most one attempt per 30 seconds, and the shared cache recovers on its own.

- **The Redis mutation queue is bounded at every level** (`tcbot/database/cache/mutations.py`, `tcbot/database/cache/twolevel/queue.py`): revocation operations were never dropped, so a dead Redis grew the queue without limit. Behavior changes: past a thousand queued mutations even a revocation is dropped with an error-level warning instead of exhausting the process memory.

- **One active ban per user is enforced by the database** (`tcbot/database/mongos.py`, `tcbot/database/bans_db.py`): two moderators reaching the warn threshold at the same moment could store two active bans, so the profile and the appeal link disagreed on which ban was real. Behavior changes: a unique partial index keeps one active ban per user, the duplicates older releases left behind are deactivated (never deleted) on the next startup, and a lost insert race reuses the winning record instead of failing the moderation action.

- **The primary group is recognised again** (`tcbot/__init__.py`): the primary-group check rejected every chat ID below zero, but Telegram group and channel IDs are negative, so the main group never matched. Behavior changes: the main group is recognised as a primary destination, federation moderation is accepted from it, join enforcement runs there, and it can no longer be disconnected, removed, or connected like an ordinary group.

- **Scheduled jobs live in the persistent job store** (`tcbot/database/scheduler.py`): the recurring schedules were registered without a job-store alias, so APScheduler put them in its auto-created in-memory store and they died with the process. Behavior changes: the warn-expiry and enforcement-sweep schedules persist across restarts, their misfire window and coalescing now apply, and the retired weekly cleanup schedule is actually removed from the database.

- **An unchanged schedule keeps its fire time** (`tcbot/database/scheduler.py`): re-registering a schedule rewrote its next run from the current clock, so a bot that restarted more often than the interval never let the daily job fire. Behavior changes: a restart keeps the persisted fire time unless the configured interval or arguments changed.

- **A scheduler that cannot start fails the boot** (`tcbot/database/scheduler.py`): the captured startup error was written to a local variable instead of the module state the boot check reads, so the bot started with a dead scheduler and logged it as ready. Behavior changes: a broken job store aborts startup instead of serving traffic without scheduled maintenance.

- **Scheduler startup no longer stalls the event loop** (`tcbot/database/scheduler.py`): the job store performs blocking database calls, which ran on the event loop and froze the webhook receiver while MongoDB was unreachable. Behavior changes: a degraded database delays startup instead of hanging the running bot.

- **The bare sync sweep keeps Admin roles from a Developer** (`tcbot/modules/sync.py`): the sweep stripped staff rank from banned or muted holders and only the targeted run carried the executor rank, so a Developer could remove an Admin role through the command. Behavior changes: a Developer cannot strip an Admin role; the scheduled sweep still reconciles every staff role.

- **A banned user cannot gain federation rank** (`tcbot/modules/helper/decorators/checks.py`, `tcbot/modules/helper/pipelines/promote_flow.py`, `tcbot/modules/helper/pipelines/promo_decision_flow.py`): the promotion paths never checked for an active ban, so a banned user could hold staff rank and moderate from any chat where the ban did not land. Behavior changes: promotions, promotion requests, and the approval of a queued request refuse a banned target and fail closed when the ban state cannot be read.

- **The promote callback applies the command path's identity refusal** (`tcbot/modules/admins.py`): the role-picker button granted roles without the refusal the command applies. Behavior changes: neither entry point grants a role to the anonymous-admin placeholder or a Telegram service account.

- **A partial threshold ban keeps the warnings of the groups it missed** (`tcbot/modules/helper/pipelines/warn_flow.py`, `tcbot/database/warns_db.py`): one successful group was enough to clear every warning of the user across the federation, leaving the failed groups with no warning and no ban. Behavior changes: warnings are cleared only where the ban landed, so the threshold can fire again in the groups where enforcement failed.

- **A concurrent threshold ban converges on one record** (`tcbot/modules/helper/pipelines/warn_flow.py`): two moderators hitting the limit at the same moment could store two active bans for one user, so the profile and the appeal link disagreed. Behavior changes: the duplicate record is deactivated, leaving one canonical active ban.

- **An invalidation is no longer undone by an in-flight read** (`tcbot/database/cache/twolevel/core.py`): a fetch that started before a revocation wrote the revoked value back into the in-memory and shared caches. Behavior changes: a revoked role or connection state is not resurrected for the cache lifetime.

- **Error reports survive a failing check** (`tcbot/utils/error_reporter.py`, `tcbot/utils/logger.py`): when the benign-error predicate itself failed, the report was dropped instead of shipped, and the failed reporting task left an unretrieved task exception in the log. Behavior changes: an unexpected failure is still reported, and the reporting task no longer produces background noise.

- **Zero duration no longer becomes a permanent mute** (`tcbot/utils/time_and_date.py`): `parse_duration` rejects a zero value instead of returning a falsy delta the mute executor coerced to permanent. Behavior changes: `/tcmute <target> 0s` now errors instead of muting forever.

- **New bans without proof no longer proceed** (`tcbot/modules/helper/pipelines/ban_flow.py`): a new ban whose proof upload returns nothing now aborts before any group is touched and explains the failure on the prompt. Behavior changes: proof-less new bans are refused instead of stored with proof zero.

- **Sync keeps admin rank for non-founder executors** (`tcbot/modules/sync.py`): targeted `/tcsync` now carries the executor role into the staff-strip step, so a developer cannot strip an admin through sync. Behavior changes: admin rows survive targeted sync unless the executor is the founder; scheduled sweeps still reconcile all roles.

- **Partial unmute no longer discards the mute record** (`tcbot/modules/helper/pipelines/mute_flow.py`): a partial fan-out now keeps the active mute so a later sync can re-drive the remaining chats. Behavior changes: partial unmute keeps the record and reports failure instead of clearing it.

- **Ownership cannot transfer to a banned user** (`tcbot/modules/helper/pipelines/transfer_flow.py`): transfer now fails closed when the target holds an active ban. Behavior changes: banned targets are refused with an unban-first message.

- **Classify failure replies instead of staying silent** (`tcbot/modules/helper/decorators/checks.py`): a failed target classification now sends a retry notice. Behavior changes: the command no longer ends without feedback.

- **Name search clamps its result limit** (`tcbot/database/users_cache.py`): non-positive and oversized limits are clamped instead of reaching the database driver. Behavior changes: none on healthy callers; invalid limits no longer scan unbounded.

- **Join requests fail closed on ban lookup outage** (`tcbot/modules/greeting.py`): a join request is declined when the ban read fails instead of proceeding, and an approved join returns early without welcome enforcement. Behavior changes: during a database outage join requests are declined rather than admitted.

- **Appeal decisions claim atomically** (`tcbot/database/bans_db.py`, `tcbot/modules/helper/pipelines/appeal_review_flow.py`): a second concurrent Approve/Reject tap loses an atomic claim and aborts instead of double executing. Behavior changes: double taps no longer produce duplicate unbans or contradictory verdicts.

- **Promotion approve claims before granting** (`tcbot/modules/helper/pipelines/promo_decision_flow.py`): the atomic resolve now runs before `add_admin`, so a winning reject is never followed by an admin grant. Behavior changes: a grant failure after a won claim leaves the request approved for manual follow-up instead of pending.

- **Cancel after Done does not abort execution** (`tcbot/modules/helper/pipelines/ban_flow.py`): cancel taps are ignored once flushing has started. Behavior changes: a late cancel no longer cancels a half executed ban.

- **Kick retry unban once** (`tcbot/modules/helper/pipelines/kick_flow.py`): a transient unban failure after kick retries once before warning. Behavior changes: transient failures no longer strand a banned user with only a kick log.

- **Permanent mute label is escaped before prompts** (`tcbot/modules/mute.py`): the duration text is escaped before reuse in MarkdownV2 prompts. Behavior changes: translated permanent text cannot break the prompt send.

- **Warn list caps at the 50 most recent** (`tcbot/modules/helper/pipelines/warn_flow.py`): the numbered render no longer loads unbounded history. Behavior changes: pathological histories render the most recent 50 with an honest total.

- **Profile role shows unknown during outage** (`tcbot/modules/helper/pipelines/check_flow.py`): a failed role lookup now renders the unknown label instead of the regular-user label. Behavior changes: `/check` no longer mislabels staff during a role-read outage.

- **Circuit breaker decays a sustained healthy run** (`tcbot/utils/circuit_breaker.py`): a long consecutive success streak clears the lifetime failure count. Behavior changes: failures spread over months no longer combine into a spurious open.

- **Sync strips stale staff rank** (`tcbot/modules/sync.py`, `tests/test_syncing.py`, `docs/features/moderation/sync.md`): bare and targeted runs clear admin, developer, and tester rows from banned or muted holders before fan-out. Behavior changes: a re-promoted banned user no longer keeps rank through a sweep.

- **Mute no longer demotes on an aborted reason** (`tcbot/modules/mute.py`): duration and reason checks now run before the auto-demote, so an overlong reason never strips a role. Behavior changes: role removal is skipped when the command aborts.

- **Unban aborts when the role survives the cleanup demote** (`tcbot/modules/unbanning.py`): when the demote clears no row, the fresh role is re-read and the unban stops if the target still holds staff rank. Behavior changes: a still-staff target keeps both role and ban instead of being unbanned with rank intact.

- **Join handling propagates shutdown** (`tcbot/modules/greeting/joins.py`): new-member handling now propagates task cancellation instead of logging it as per-item failure. Behavior changes: none during normal operation.

- **Sync treats unexpected refusals as failures** (`tcbot/modules/syncing/core.py`, `docs/features/moderation/sync.md`): membership and enforcement errors now count through the shared benign check only, so non-benign refusals surface in the failed total. Behavior changes: some skips now read as failures.

- **Cache fetch keeps mutual exclusion** (`tcbot/database/cache/twolevel/core.py`): a finishing fetch removes only its own lock, so concurrent misses for the same key cannot run two database fetches after a lock handoff. Behavior changes: none on single-threaded use; shared misses fetch once.

- **Warn expiry timeout fails the job** (`tcbot/database/scheduler/jobs.py`): a hung expiry now raises instead of returning normally, so the daily job and the cron endpoint report the incomplete run instead of success. Behavior changes: a timeout answers failure instead of success.

- **Cancelled reads no longer render as empty** (`tcbot/modules/helper/pipelines/stats_flow.py`, `tcbot/modules/check.py`): shutdown cancellation propagates from the overview, roster, and self-check reads instead of rendering as zeroes or a clean record. Behavior changes: none during normal operation.

- **Skip-reason checks rank like Done and Skip** (`tcbot/modules/helper/pipelines/reason_flow.py`): advancing without a reason now verifies the tapper still holds rank, matching the proof Done and Skip taps. Behavior changes: a demoted moderator's skip tap ends the flow with a refusal instead of advancing.

- **Shutdown cancellation propagates instead of reading as failure** (`tcbot/__main__.py`, `tcbot/serverless.py`, `tcbot/modules/connecting.py`, `tcbot/modules/disconnecting.py`, `tcbot/modules/helper/pipelines/demote_flow.py`, `tcbot/modules/helper/pipelines/promote_flow.py`, `tcbot/modules/helper/pipelines/appeal_submit_flow.py`, `tcbot/modules/helper/pipelines/mute_flow.py`, `tcbot/modules/helper/pipelines/connected_flow.py`): parallel reads and deliveries now propagate task cancellation, so shutdowns no longer log as per-item failures or complete as success. Cache warm-up, startup, shutdown, and webhook paths follow the same contract. Behavior changes: none during normal operation.

- **Prefix-wide Redis clear is bounded per operation** (`tcbot/database/cache/twolevel.py`, `docs/architecture/database.md`): each scan and unlink now has its own 2.0 second bound, so a stalled sweep aborts instead of holding the ordered mutation tail. Behavior changes: none on healthy reads.

- **Member-cache harvest stays bounded under burst** (`tcbot/__main__.py`, `docs/architecture/database.md`): background identity upserts now cap at 20 in-flight tasks and skip beyond that, so a burst across many groups cannot pile up against the database pool. Behavior changes: none; the next update refreshes skipped names.

- **Scheduler stop always clears module state** (`tcbot/database/scheduler/lifecycle.py`, `docs/architecture/database.md`): a background-task exception is logged and still clears the task and schedule handles, and cancellation of the stop itself clears before propagating, so the next start never races a dying task. Behavior changes: none on the happy path.

- **Warn expiry reports partial failure as a job failure** (`tcbot/database/scheduler/jobs.py`, `docs/architecture/database.md`): when one delete fails and the other succeeds, expiry now raises after the error log instead of returning normally, so the scheduler and the cron endpoint surface the incomplete run. Behavior changes: partial expiry answers failure instead of success.

- **Stale schedule removal failures log at warning level** (`tcbot/database/scheduler/schedules.py`, `docs/architecture/database.md`): removing a disabled or legacy schedule now logs a warning when the removal fails for a reason other than not present, so a stale schedule that keeps firing is visible in the logs. Behavior changes: log level only.

- **Unban, kick, broadcast, and appeal notifications propagate cancellation** (`tcbot/modules/helper/pipelines/unban_flow.py`, `tcbot/modules/helper/pipelines/kick_flow.py`, `tcbot/modules/broadcasting.py`, `tcbot/modules/helper/pipelines/appeal_review_flow.py`): the final log, reply, and notification reads now propagate task cancellation instead of logging it as per-item failure. Behavior changes: none during normal operation.

- **Appeal review blocks self-review and demotes staff before approval** (`tcbot/modules/helper/pipelines/appeal_review_flow.py`, `docs/features/appeals.md`): a banned user who is later promoted cannot approve or reject their own appeal, and an approved appeal now demotes a still-staff target before unbanning, mirroring manual unban. A role lookup outage or demote failure keeps the review card untouched. Behavior changes: self-review taps alert instead of deciding; approved staff targets lose their role before unban.

- **Cancel buttons honour the prompt opener** (`tcbot/modules/helper/keyboards/admin.py`, `tcbot/modules/admins/promote.py`, `tcbot/modules/admins/demote.py`, `tcbot/modules/admins/shared.py`, `i18n/en-US/admins.toml`, `i18n/id-ID/admins.toml`, `docs/features/roles/promote.md`, `docs/features/roles/demote.md`, `docs/features/roles/roles.md`): new role-picker and demote confirmation cancels carry the staff member who opened the prompt, so a different tapper gets a not-owner alert and the prompt stays live. Legacy cancel taps keep working. Reason-flow cancels are already scoped by the conversation handler. Behavior changes: cross-staff cancel taps alert instead of collapsing the prompt.

- **Revocation cache writes survive queue saturation** (`tcbot/database/cache/twolevel.py`, `docs/architecture/database.md`): single-key deletes and writes for role, connection, group-list, and owner caches are never dropped when the mutation queue is full, so a revoked privilege cannot stay visible to other processes until the key TTL. Display-name hints remain droppable. Behavior changes: none on healthy reads; revocations land even under burst.

- **Cancelled Redis predecessor no longer drops its successors** (`tcbot/database/cache/twolevel.py`, `docs/architecture/database.md`): each FIFO mutation shields its predecessor and only aborts on its own cancellation, so one cancelled task cannot cascade-cancel the tail. Behavior changes: none on the happy path; later mutations still run after an earlier cancellation.

- **Cache split into queue and core modules** (`tcbot/database/cache/twolevel/`): the FIFO mutation queue now lives in its own submodule with a thin re-exporting package, keeping every file within the size budget again. Public imports, cache keys, and queue ordering are unchanged.

- **Appeal verdicts live in one module** (`tcbot/modules/helper/pipelines/appeal_review_flow.py`): the approve and reject executors share one file with the log helper. Callback data and verdict behaviour are unchanged.

- **Transfer and warn-manage deliveries propagate cancellation** (`tcbot/modules/admins/transfer.py`, `tcbot/modules/helper/pipelines/warn_flow.py`): the final log and reply reads now propagate task cancellation instead of logging it as per-item failure. Warn, index, and sync sweeps already propagate manually. Behavior changes: none during normal operation.

- **Connect fails closed on database outage** (`tcbot/modules/connecting.py`, `tcbot/modules/helper/pipelines/connected_flow.py`, `docs/features/moderation/connecting.md`): the manual and bot-added connect paths now reply with a retry notice, or drop the event, when the connection-state reads fail instead of treating the outage as not connected. Behavior changes: outage connects show a failure notice instead of proceeding to join.

- **Join decision refuses primary groups** (`tcbot/modules/helper/pipelines/connected_flow.py`, `docs/features/moderation/connecting.md`): tapping Connect on a primary-group prompt now answers and returns without connecting, matching the command and bot-added guards. Behavior changes: none on normal prompts; primary-group taps no longer create a federation row.

- **Silence-window ban flush re-checks executor rank** (`tcbot/modules/helper/pipelines/ban_flow.py`, `docs/features/moderation/banning.md`): the background flush now checks that the moderator still meets Developer rank before enforcing, so a moderator demoted during proof collection can no longer ban from a stale session. A role lookup outage aborts the flush the same way. Behavior changes: demoted moderators no longer enforce through a silence flush.

- **Mongo circuit counts only transient errors** (`tcbot/utils/circuit_breaker.py`, `tcbot/database/mongos/client.py`, `docs/architecture/database.md`): the breaker now counts connectivity failures, timeouts, and retryable write concerns toward opening, while application errors propagate without recording a failure. Client-side operation timeouts are recognised through the documented timeout property. Behavior changes: a bad write no longer opens the database circuit; outages still open it.

- **Dead MTProto auth key parks instead of flooding reports** (`tcbot/database/mtproto/lifecycle.py`, `tcbot/__main__.py`, `tcbot/utils/error_reporter.py`, `docs/getting-started/setup.md`): a missing auth key, including when it surfaces during session restart, now parks MTProto once with one operator card and keeps the bot on Bot-API-only until the session docs are purged and one instance reboots. Behavior changes: a dead key no longer repeats as code-bug reports while enforcement stays online.

- **Database outages degrade instead of flooding error reports** (`tcbot/database/mtproto_store/retry.py`, `tcbot/database/mtproto_store/lease.py`, `tcbot/__main__.py`, `tcbot/database/mtproto/lifecycle.py`, `tcbot/utils/error_reporter.py`): MTProto writes degrade at once on connectivity failures and an open database circuit without crashing update handling, the owner lease refuses during an outage instead of guessing, lease beats during an outage log a warning without a traceback, background task failures surface their real type so outages stay suppressed at the source, and error cards label a database circuit separately from a Telegram circuit. Behavior changes: an outage no longer produces a steady stream of MTProto install reports, and identity lookups now degrade as before.

- **Fan-out partial failures no longer masquerade as code bugs** (`tcbot/utils/dispatch.py`, `tcbot/modules/helper/pipelines/ban_flow.py`, `unban_flow.py`, `mute_flow.py`, `mute_flow.py`, `appeal_review_flow.py`, `tcbot/utils/error_reporter.py`): the error-level summary now attaches a representative transient exception as `exc_info`, so the reporter classifies it by its real Telegram type, shows a traceback, and gives a retry hint instead of "[?] Unknown / Needs a code fix". The reporter also stops claiming a traceback exists for records with no exception. Behavior changes: partial-failure reports now name the actual transient error and its recovery action.

- **Concurrent first-warns no longer drop one warning** (`tcbot/database/warns_db/records.py`, `counters.py`, `tests/test_warn_counter_race.py`): when two moderators warn the same user in the same chat for the first time at once, the counter increment retries after losing the insert race, and the backfill path re-reads the winner's count instead of failing. Behavior changes: both warnings land instead of one getting a database-failure retry reply.

- **Owner transfer cleans up split-brain rows with a retry** (`tcbot/database/users_roles.py`, `tests/test_set_owner_cleanup.py`): the convergence delete backs off and retries transient failures, and a persistent failure logs explicit operator guidance (which row to remove) before the transfer still fails closed. Behavior changes: none on the happy path; a one-off database blip no longer strands two owner rows.

- **Test stubs satisfy the type checker again** (`tests/test_ban_flush_cleanup.py`): the zombie update/context stubs carry their type-suppression comments on the argument lines where the checker reports them, so the CI type-check gate passes on the default branch. Behavior changes: none.

- **Regression coverage restored** (`tests/`, `.github/workflows/test-pytest.yml`): 49 check modules covering health, i18n, dispatch, formatter, MTProto, and moderation flows are active again. Two retry-write checks now expect the graceful-degrade contract: an exhausted or non-transient `WriteConcernError` logs and returns instead of re-raising, preserving Pyrogram's background task. CI's test workflow now executes the checks instead of collecting zero items.

- **Unban no longer skips staff-target demote on degraded identity** (`tcbot/modules/unbanning.py`): federation staff-ness now comes from the fail-closed role read, so a transient `identity.classify` failure no longer drops the demote-before-unban cleanup. Behavior changes: none on the happy path.

- **Auto-demote aborts when the role survives a no-op removal** (`tcbot/modules/helper/pipelines/demote_flow.py`): a no-row removal now re-reads the live role and aborts only when the role still resolves, so a banned, kicked, or muted user cannot keep a federation role through split-brain. Behavior changes: none on the happy path.

- **Group migration cleans up a stale pending row** (`tcbot/database/groups_db.py`): a `DuplicateKeyError` on the pending-joins repoint now deletes the stale old row instead of leaving a dangling pending document. Behavior changes: none on the happy path.

- **MTProto writes degrade instead of crashing update handling** (`tcbot/database/mtproto_store/retry.py`): non-transient store failures are logged and returned instead of propagating into Pyrogram's background task. Behavior changes: update handling continues instead of dying on a store error.

- **MTProto lease claim no longer grants a live foreign lease** (`tcbot/database/mtproto_store/retry.py`): the retry helper now catches only `WriteConcernError`, so control-flow errors such as `DuplicateKeyError` propagate to `claim_owner`, which refuses a lease already held by another live owner. Behavior changes: none on the happy path.

- **Sync re-applies mutes with aware datetimes** (`tcbot/modules/syncing/core.py`): mute expiry values are normalized to UTC before being sent to Telegram. Behavior changes: none on the happy path.

- **Connection requests reject anonymous admins** (`tcbot/modules/connecting.py`): groups posting as the anonymous admin can no longer submit an unattributable connection request. Behavior changes: anonymous-admin requests are refused.

- **Admin harvest is bounded** (`tcbot/modules/helper/pipelines/connected_flow.py`): identity writes now run through the bounded gather helper instead of an unbounded one. Behavior changes: none.

- **Transient Telegram errors no longer flood the error channel** (`tcbot/__main__.py`): `NetworkError`, `TimedOut`, `RetryAfter`, and OS-level network errors are logged at warning/debug and skipped by both the PTB handler and the asyncio exception handler instead of being shipped as code bugs. Behavior changes: transient connectivity blips stop appearing as "Needs a code fix" reports.

- **Cancellation propagates in moderation flows** (`connected_flow.py`, `warn_flow.pyissue.py`, `mute_flow.py`): `throw_if_cancelled` now runs after the parallel log, reply, and connection gathers, so shutdown is not misreported as per-item failure. Behavior changes: none on the happy path.

- **Container image ships the message catalog** (`Dockerfile`): the build copies `i18n/` next to the package so the first render finds its templates. Behavior changes: Docker deploys boot instead of failing every handler.

- **Stats search buttons read real labels** (`tcbot/modules/helper/keyboards.py`): the Search and New Search buttons use the shared button catalog instead of missing keys. Behavior changes: the buttons show words instead of key markers.

- **Boot guides name the MTProto credentials** (`README.md`, `AGENTS.md`, `replit.md`, `config.env.example`, `docs/getting-started/setup.md`): `API_ID` / `API_HASH` are listed as required wherever the other boot values are, and the template ships them as active entries instead of comments. Behavior changes: fresh deploys following the guides boot instead of refusing to start.

- **Ban-detail reason renders literally** (`tcbot/modules/helper/ban_info.py`): moderator free text now passes through the render engine instead of bypassing it. Behavior changes: reasons containing markup characters show as written instead of breaking or reshaping the card.

- **Cancelled callbacks propagate instead of reading as failures** (`tcbot/modules/helper/parse_editmsg.py`, `reason_flow.py`, `connected_flow.py`, `tcbot/modules/helper/locale.py`): answer-and-render paths re-raise cancellation, and locale resolution tolerates malformed updates. Behavior changes: none during normal operation; shutdowns no longer log as data-fetch failures.

- **Stale documentation swept** (`docs/architecture/database.md`, `helpers.md`, `workflows.md`, `utilities.md`, `docs/features/roles/roles.md`, `demote.md`, `docs/reference/keyboard-styles.md`, `.agents/rules/docs-sync.md`): keyboard ownership, warn counter repair and merge, role validation, and the ID-only mention contract match the code; forbidden characters, the Replit runtime version, and the type-check scope are corrected. Behavior changes: none, docs only.

- **Repository maps and guides match the code** (`AGENTS.md`, `docs/architecture/database.md`, `helpers.md`, `repository-map.md`, `docs/features/moderation/disconnecting.md`, `docs/features/roles/roles.md`): command names, callback-only panels, the tree, ownership transfer, warn migration, keyboard ownership, the MTProto startup step, and the `/rmtc` primary guard describe current behavior. The dependency manifest pins the MTProto client range. Behavior changes: none, docs only.

- **Replit webhook port corrected to 8080** (`.replit`, `replit.md`): public traffic only reaches local port 8080, so serving the webhook on the 5000 default left every Telegram delivery dying at the proxy and the bot never replied. The port mapping is back to 8080 only and the deployment guide names the required value. Behavior changes: webhook deliveries reach the bot on Replit.

- **Runner forwards the MTProto credentials** (`.github/workflows/run-bot.yml`, `docs/operations/ci-cd.md`): the merge that made `API_ID` / `API_HASH` mandatory at boot never added them to the runner env, so every run crashed on startup until the watchdog gave up after five rapid deaths. The workflow now forwards both secrets and the guide lists them as required. Behavior changes: runs boot instead of fail-looping. Repository secrets `API_ID` and `API_HASH` still need to be set once in the repo settings.

- **MTProto store retries transient write errors** (`tcbot/database/mtproto_store.py`): Pyrogram's background `handle_updates()` task persists update states through the MongoDB store. A transient replica-set failover (`WriteConcernError` code 11602 / `InterruptedDueToReplStateChange`) with the `RetryableWriteError` label now retries up to 3 times with exponential backoff instead of crashing the background task and flooding the error channel. All write operations (scalar upserts, peer updates, username writes, update-state merges, and deletes) benefit from the retry wrapper. Behavior changes: brief replica-set elections no longer produce unhandled task exceptions.

- **Single-owner MTProto lease plus invalidated-session parking** (`tcbot/database/mtproto.py`, `mtproto_store.py`, `tcbot/__main__.py`, `tcbot/utils/error_reporter.py`, `docs/getting-started/setup.md`, `docs/architecture/database.md`): only the instance holding a short-lived MongoDB lease keeps a live MTProto connection, so two simultaneous instances can no longer kill the shared auth key with `406 AUTH_KEY_DUPLICATED`; losers serve Bot-API-only until takeover. When Telegram reports an invalidated key, the client parks once with a loud actionable card and every resolver degrades instead of crash-looping, and error fingerprints ignore task IDs and hex addresses so one incident ships one card instead of a flood. A rejected stored key at connect time also degrades instead of aborting boot, so enforcement stays online while the session awaits the operator purge-and-restart. Behavior changes: a second simultaneous instance no longer connects MTProto; a dead session degrades instead of looping.

- **Stats search detail parses callback data safely** (`tcbot/modules/stats.py`): the callback query handler for search result detail now catches both `ValueError` and `IndexError` when parsing the index from callback data, preventing a crash on malformed input. Behavior changes: malformed search callbacks no longer raise unhandled exceptions.

- **Ban-detail admin lookup logs failures** (`tcbot/modules/helper/ban_info.py`): a failed admin-mention data lookup now logs at debug level instead of silently degrading, giving operators a trace when the numeric ID fallback is used. Behavior changes: none visible to users.

- **MTProto store type annotations completed** (`tcbot/database/mtproto_store.py`): `_coll()` and `_accessor()` now have explicit return type annotations, and `update_usernames()` stores `updated_on` as `int` to match `update_peers()`. Behavior changes: none.

- **Utils package exports match public API** (`tcbot/utils/__init__.py`): `i18n`, `pagination`, and `transport` modules are now listed in `__all__` alongside the existing exports, matching their actual usage across the codebase. Behavior changes: none.

- **Pagination helper typed for datetime** (`tcbot/utils/pagination.py`): `date_or_unknown()` parameter is now `datetime | None` instead of `Any`, catching type errors at call time. Behavior changes: none.

- **Link-preview default has one owner** (`tcbot/serverless.py`, `tcbot/__main__.py`): the serverless transport imports the constant instead of redefining it. Behavior changes: none, identical preview suppression on both transports.

- **Redis hint follows the uv-only rule** (`tcbot/database/redis_client.py`): the missing-extension error points at `uv add` instead of `pip install`. Behavior changes: message text only.

- **Module logger ordering hardened** (`tcbot/database/mongos.py`): the logger is defined before the DNS helper that references it. Behavior changes: none.

- **Scheduler startup cannot hang on a stuck task** (`tcbot/database/scheduler.py`, `tests/test_scheduler_start.py`): the readiness-timeout path unwinds the background task with the same bounded 2-second gather as the cancellation path. Behavior changes: a task ignoring cancellation no longer stalls boot past the bound; a warning names it.

- **Promotion queue names the already-pending case** (`tcbot/database/queues_db.py`, `tests/test_queues_enqueue.py`): an `AlreadyPendingError` (still a `DuplicateKeyError` for callers) is raised at once when the one-pending-per-user index rejects, using the server key pattern with a message fallback; the blind retry stays for genuine ID collisions. Behavior changes: none for callers; pending requests skip the wasted retry.

- **Demote clears both collections concurrently** (`tcbot/modules/helper/pipelines/demote_flow.py`): the two independent removes run in one gather with identical return semantics. Behavior changes: none, same result with one round trip.

- **Health and webhook paths gain regression cover** (`tests/test_alive_health.py`): 16 new checks pin the queue-depth field, the decode-400 versus enqueue-503/500 split, secret rejection, and scheduler/circuit degraded verdicts. Behavior changes: none, suite grows 8 to 24 in this file.

- **Audit-wave behavior pinned by tests** (`tests/test_wave_regressions.py`, `tests/test_queues_enqueue.py`, `tests/test_roles_cache.py`): harvest budget cutoff, shared flood handling, verbatim secret redaction, list-or-CSV env parsing, prefix-copy semantics, sorted sync pairing, cron 405, queue collision versus pending paths, and cached-versus-outage role reads. Behavior changes: none, 18 new checks.

- **Pre-commit hooks match the repo pins** (`.pre-commit-config.yaml`): the ruff hook moves to the locked version so local hooks and CI enforce identical rules; the whitespace and end-of-file fixers were applied once across 16 files. Behavior changes: none.

- **Additional menu uses the shared answer-and-edit path** (`tcbot/modules/additional.py`): the manual acknowledge-and-edit block is replaced by the helper every other menu uses, which also removes references to an undefined logger that would have raised on the failure path. Behavior changes: tapping the menu no longer risks an unhandled error when the edit fails.

- **Proof conversation ends after a silence flush executes the ban** (`tcbot/modules/helper/pipelines/ban_flow.py`, `tests/test_ban_flush_cleanup.py`, `docs/features/moderation/banning.md`): late messages, media, Done taps, and commands arriving after the background flush end the leftover conversation silently instead of nagging for proof, opening orphan sessions, or claiming no ban was issued. Behavior changes: post-ban messages no longer receive proof prompts; timed-out commands after an executed ban end quietly.

- **Unmute keeps the record on total enforcement failure** (`tcbot/modules/helper/pipelines/mute_flow.py`, `tests/test_mute_partial_failure.py`, `i18n/en-US/muting.toml`, `i18n/id-ID/muting.toml`, `docs/features/moderation/muting.md`): when no group could be unrestriced the reply asks for a retry and the active-mute row stays, so a re-run re-drives the full fan-out instead of announcing a restore while every chat is still muted. Behavior changes: total-failure unmutes no longer clear the record.

- **Group management re-checks staff state fresh** (`tcbot/modules/helper/identity.py`, `tcbot/modules/disconnecting.py`, `tcbot/modules/language.py`): the disconnect and group-language write gates now read the staff role directly instead of the cached value, so a demotion takes effect at once. Behavior changes: a demoted admin can no longer disconnect a group or save its language during the old cache window.

- **Empty help and privacy taps dismiss the spinner** (`tcbot/modules/help/callbacks.py`, `tcbot/modules/privacy.py`): callbacks carrying no data now answer before returning instead of leaving the client spinner hanging. Behavior changes: malformed taps dismiss the spinner instead of timing out.

- **Check views propagate shutdown instead of rendering empty** (`check_flow.py`, `netspeed.py`): cancelled parallel reads now propagate instead of rendering as empty states, matching every other moderation read path. Behavior changes: none during normal operation.

- **Debug diagnostics reach the log stream** (`tcbot/utils/logger.py`): the logging bridge now honors each logger's level, so debug-level traces (failed membership probes, degraded lookups) are no longer swallowed when the bot runs above debug. Behavior changes: operators see the degraded-lookup traces in logs again; production stays quiet at its configured level.

- **Bot starts regardless of module load order** (`tcbot/utils/time_and_date.py`, `tcbot/utils/logger.py`, `tcbot/utils/i18n.py`): the time helper loads the message catalog lazily instead of importing it at module level, so logging, time, and catalog load in any order without a circular-import failure. Behavior changes: none on the happy path; startup no longer depends on which module imports first.

- **Speedtest follows speedtest.net** (`tcbot/modules/netspeed.py`, `tests/test_netspeed.py`): config, server list, latency, download, and upload now run against speedtest.net with the Ookla agent, closest-server selection, and concurrent transfers, returning real client ISP and country. Behavior changes: `/speedtest` reports the speedtest.net best server; results keep the same fields.

- **Role picker shows the live name on a cache miss** (`tcbot/modules/admins.py`, `tests/test_promote_live_name.py`): the promote role callback resolves the target live before rendering the Done text when the cached name is the numeric fallback, so newly seen users render by name instead of ID. Behavior changes: picker confirmations for uncached users show the Telegram name.

### Removed

- **Unused helpers and forwarding wrappers** (`tcbot/utils/time_and_date.py`, `tcbot/database/mtproto.py`, `tcbot/modules/helper/replies.py`, `tcbot/modules/helper/pipelines/stats_flow.py`, `tcbot/modules/helper/pipelines/check_flow.py`, `tcbot/modules/helper/decorators/auth.py`, `tcbot/modules/helper/keyboards/__init__.py`): a speculative timestamp helper, a configuration alias, a permission notice with no renderer, four keyboard wrappers that only forwarded, a placeholder alias, and an unused import. Behavior changes: none; the unused permission notice is removed from both locale catalogs.

- **Motor and speedtest-cli leave the dependency graph** (`pyproject.toml`, `uv.lock`): the database layer now runs on synchronous PyMongo and `/speedtest` on speedtest.net, so neither package is needed. Behavior changes: none for operators beyond the entries above.

- **Unused UTC display helper removed** (`tcbot/utils/time_and_date.py`, `docs/architecture/utilities.md`): `utc_now_str()` had no callers and its rows in the utilities guide are gone. Display rendering stays on `fmt_dt()`. Behavior changes: none.

- **Appeal log handle removed** (`tcbot/__init__.py`, `tcbot/modules/helper/pipelines/appeal_submit_flow.py`, `config.env.example`, `README.md`, `AGENTS.md`, `CLAUDE.md`, `docs/getting-started/setup.md`, `docs/operations/ci-cd.md`, `docs/features/appeals.md`, `.github/workflows/run-bot.yml`): the separate handle setting is gone and the instruction handle follows the public logs link instead. `APPEALS` stays the single appeal destination for channel, group, or forum thread use. Behavior changes: an existing handle value is ignored; update the public logs link instead.

- **Appeal discussion topic removed** (`tcbot/__init__.py`, `tcbot/modules/helper/pipelines/appeal_submit_flow.py`, `tcbot/modules/helper/parse_logmsg/appeals.py`, `config.env.example`, `README.md`, `AGENTS.md`, `CLAUDE.md`, `docs/getting-started/setup.md`, `docs/operations/ci-cd.md`, `docs/features/appeals.md`, `docs/architecture/workflows.md`, `.github/workflows/run-bot.yml`): the separate thread setting is gone and the main-group review card posts to general. `APPEALS` stays the single appeal destination for channel, group, or forum thread use. Behavior changes: an existing topic value is ignored; review cards no longer land in a dedicated main-group topic.

- **Unused log and navigation helpers removed** (`tcbot/modules/helper/parse_logmsg/core.py`, `tcbot/modules/helper/pipelines/stats_flow.py`): two `LogBuilder` block helpers and one stats back-row alias had no callers. The live builders and the central keyboard factories stay. Behavior changes: none.

- **TCF Bot 24/7 runner disabled** (`.github/workflows/run-bot.yml` → `.github/workflows.disabled/`): the self-chaining GitHub Actions runner is moved out of the active workflows directory so it no longer schedules or runs. Behavior changes: the bot no longer auto-runs via GitHub Actions; host it elsewhere.

- **Dead locale scope helper removed** (`tcbot/modules/helper/locale.py`, `docs/architecture/helpers.md`): `chat_scope()` had no callers anywhere in code, tests, or docs examples; `language._chat_scope` remains the single mapping and keeps its test. Behavior changes: none.

- **Dead role-comparison helper removed** (`tcbot/database/users_roles.py`): `can_act_on()` had no callers; executor-versus-target checks go through the decorator path. Behavior changes: none.

- **Dead identity-cache probe removed** (`tcbot/database/users_cache.py`): `has_recent_identity_attempt()` had no callers; resolvers read the mention cache directly. Behavior changes: none.

- **Agent tooling rules removed** (`.agents/rules/tooling-skills-use.md`, `AGENTS.md`, `.agents/rules/`, `.agents/skills/`): the combined tooling and validation file is gone, so workflow follows `AGENTS.md` and checks follow `docs/operations/ci-cd.md`. Behavior changes: none for operators; guidance only.

- **Standalone edit and log helpers removed** (`tcbot/modules/helper/parse_editmsg.py`, `tcbot/modules/helper/parse_logmsg/`): both paths are gone; all callers now import from `tcbot/modules/helper/messages.py`. Behavior changes: external callers that imported the old paths must switch modules; bot behavior is unchanged.

- **Skills directory removed** (`.agents/skills/`, `skills-lock.json`): the feature-review and MongoDB optimizer skills, their reference guides, and the skill manifest are gone. Behavior changes: none for operators; agent guidance now lives only in `.agents/rules/`.

- **Unused ban helpers removed** (`tcbot/database/bans_db.py`, `docs/architecture/database.md`): `deactivate_ban` and `set_review` had no callers; `deactivate_all_active_bans`, `deactivate_extra_active_bans`, and `set_review_if_absent` are the live helpers. Behavior changes: none.

### Documentation

- **Database and performance documentation match the implementation** (`docs/architecture/database.md`, `docs/operations/performance.md`): the database worker pool, the per-call budget, the lazy Redis reconnect, the bounded mutation queue, the one-active-ban constraint, and the hot-path benchmark are now described as implemented.

- **Developer docs match the implementation** (`AGENTS.md`, `.agents/rules/asyncio-gather-rules.md`, `docs/architecture/*.md`, `docs/features/**/*.md`, `docs/operations/*.md`, `docs/reference/*.md`, `README.md`): the configuration model, the scheduler's persistent job store and off-loop startup, the sync rank gate, the promotion ban guard, the warn-threshold clearing rule, the current callback shapes, the shipped locale, and the CI file-size gate are now described as implemented.

- **Env table and module examples match the loader** (`CLAUDE.md`, `config.env.example`, `docs/getting-started/setup.md`, `docs/architecture/repository-map.md`): the required founder identity, the `SENTRY_DSN` option, the live module names, and the `id-ID` catalog location now match the code. Behavior changes: none, docs only.

- **Dependency, proofs, and coverage documentation refreshed** (`docs/getting-started/setup.md`, `docs/operations/ci-cd.md`, `docs/architecture/database.md`, `docs/architecture/utilities.md`, `AGENTS.md`): PyMongo, the `PROOFS` default, the `SENTRY_DSN` option, and the coverage-backed test workflow are aligned with the implementation. Behavior changes: none for operators.

- **Appeal and pool references match the tree** (`docs/features/appeals.md`, `docs/architecture/workflows.md`, `docs/operations/performance.md`): the appeal facade names the `appeal_submit_flow.py` module instead of a directory, the unban section names `unban_flow.py`, and the getUpdates pool size is credited to its lifecycle owner. Behavior changes: none, docs only.

- **Setup and run guides match the config surface** (`README.md`, `config.env.example`, `docs/getting-started/setup.md`, `.github/workflows/run-bot.yml`): error reports fall back to the owner DM when empty, the appeals community link is listed and forwarded, removed federation chat vars and the exec button are gone, and Docker port text follows the configured port. Behavior changes: none, docs only.

- **Moderation guides name the federation origin gate** (`docs/features/moderation/banning.md`, `muting.md`, `kicking.md`, `warnings.md`, `sync.md`): each guide states which commands allow DM and which require a connected or primary group, and that outages block with a retry notice. Behavior changes: none, docs only.

- **Circuit wording matches the breaker** (`tcbot/utils/circuit_breaker.py`): the threshold is now described as transient failures that successes do not reset, so a partial outage with interleaved successes can still trip it. Behavior changes: none, wording only.

- **Guides match the disabled runner** (`README.md`, `AGENTS.md`, `.agents/rules/docs-sync.md`, `docs/operations/ci-cd.md`, `docs/architecture/helpers.md`, `docs/architecture/repository-map.md`, `docs/getting-started/setup.md`, `CONTRIBUTING.md`, `config.env.example`, `docs/architecture/helpers.md`, `docs/architecture/database.md`, `docs/features/roles/roles.md`, `.agents/rules/security-rules.md`, `docs/features/moderation/check.md`, `docs/features/statistics.md`, `.pre-commit-config.yaml`): the runner is documented as parked, missing contributor links and stale role-check references are gone, startup ownership and discovery match the runtime package, the session namespace ships active, and the public check and stats panes are marked public by design. Behavior changes: none, docs only.

- **CI secrets list corrected** (`docs/operations/ci-cd.md`): the runner forwards `SYNC_INTERVAL_HOURS` and the community links; only `CRON_SECRET` is not forwarded. Behavior changes: none, docs only.

- **Repository map includes the startup packages** (`docs/architecture/repository-map.md`, `AGENTS.md`): the config and runtime packages, the shared migration helper, and the thin entry module are documented. Behavior changes: none, docs only.

- **Test command and dispatch docs corrected** (`README.md`, `docs/architecture/utilities.md`): the CI test command example includes the parallel flag, and the removed fan-out counting helper is gone from the dispatch table. Behavior changes: none, docs only.

- **Guides follow the package layout** (`AGENTS.md`, `docs/architecture/modules.md`, `workflows.md`, `repository-map.md`, plus file-path references across the feature guides): module discovery documents packages, the workflows rule names `*_flow/` packages, and every split-module path reads in package form. Behavior changes: none, docs only.

- **Shorter type-check command in every guide** (`README.md`, `AGENTS.md`, `PROMPT.md`, `CONTRIBUTING.md`, `docs/README.md`, `docs/getting-started/setup.md`): the documented command no longer requests anything extra since the checker already ships with the development dependencies, and all six guides now cover the whole tree. Behavior changes: none, docs only.

- **Allowlist/denylist terminology standardized** (`docs/getting-started/setup.md`, `docs/architecture/modules.md`): the `MODULES_LOAD` and `MODULES_NO_LOAD` descriptions now use "allowlist" and "denylist" instead of "whitelist" and "blacklist", matching the project's canonical terminology in AGENTS.md and code-style.md. Behavior changes: none, docs only.

- **Comment rules gain an expert redundancy standard** (`.agents/rules/comment-style.md`): one explanation lives in exactly one place, helper contracts are never restated at call sites, branch and constant restatements go unconditionally, unique contracts relocate instead of vanishing, and repeated rationale hoists to the owning helper or docs page. Behavior changes: none, docs only.

- **Example placeholder values corrected** (`config.env.example`): the `OWNER_ID` example now uses a clearly fictitious placeholder (`123456789`) instead of a value that could be mistaken for a real user ID. Behavior changes: none, docs only.

- **Stale reply-function references corrected across six feature guides** (`docs/features/moderation/muting.md`, `unbanning.md`, `kicking.md`, `connecting.md`, `disconnecting.md`, `docs/architecture/helpers.md`): every `replies.ERR_CANNOT_RESOLVE`, `replies.ERR_GROUP_ONLY`, `replies.ERR_ROLE_VERIFY`, `replies.ERR_GROUP_NOT_FOUND`, `_ERR_ROLE_CHECK_FAILED`, `_ERR_OWNER_ONLY`, `_ERR_BOT_PERMS_VERIFY`, and `_ERR_COMPLETE_JOIN` constant reference is replaced with the actual lowercase function call or descriptive prose, and the `users_cache` mention in the helper-usage rules is corrected to `users_roles`. Behavior changes: none, docs only.

- **Guides match the dispatcher and the mention helper** (`AGENTS.md`, `docs/architecture/utilities.md`, `docs/operations/performance.md`): the agent guide lists `MTPROTO_SESSION` alongside the other runtime values, the formatter rows name `user_ref` instead of the removed alias, and the dispatch sections cover the bounded database gather alongside `fan_out`. Behavior changes: none, docs only.

- **Feature guides renumbered and de-rotted** (`docs/features/moderation/banning.md`, `disconnecting.md`, `check.md`, `connecting.md`, `muting.md`, `appeals.md`): duplicated and skipped step numbers fixed, a stale variable name corrected to MarkdownV2 reality, rotted file-and-line references reduced to symbol names, and primary-group mentions clarified to env names versus config properties. Behavior changes: none, docs only.

- **Batch mention cache description corrected** (`docs/architecture/database.md`): the first-name batch path now states the shared triple fetch with cache population and the four-field covered index, replacing the retired no-write-back note. Behavior changes: none, docs only.

- **Unmute executor order corrected** (`docs/features/moderation/muting.md`): the steps now read guard, permissions, group fetch, fan-out, record clear before announce, then log and reply, matching the implementation. Behavior changes: none, docs only.

- **Kick executor order corrected** (`docs/features/moderation/kicking.md`): the steps now start with the audit write and its fail-closed retry, then ban, upload, re-demote, and the parallel unban plus log post. Behavior changes: none, docs only.

- **Flow and database placement rules clarified** (`AGENTS.md`, `docs/architecture/workflows.md`, `docs/architecture/repository-map.md`, `.agents/rules/code-style.md`): flows and database helpers stay flat while they fit the file budget and split into packages after that, so the existing modules and packages both satisfy the rule. Behavior changes: none, docs only.

- **Em dash rule file carries no literal** (`.agents/rules/comment-style.md`, `.github/workflows/auto-fix.yml`, `dependency-update.yml`): the rule text and the CI sanitizers use the escaped form with identical replacement output, so the forbidden-character scan reports empty. Behavior changes: none, docs and workflow text only.

- **Demotion module path corrected across the guides** (`docs/architecture/helpers.md`, `workflows.md`, `docs/features/moderation/banning.md`, `docs/features/roles/demote.md`, `roles.md`): the demote helper is a file, not a package, and the guides now name it correctly. Behavior changes: none, docs only.

- **Database guide matches the current indexes and startup** (`docs/architecture/database.md`): the covered index names its fourth field, the owner, staff, and scheduler signatures carry their fresh and runner arguments, and the startup wiring describes the shared setup path both transports call. Behavior changes: none, docs only.

- **Role prompt guides match the owner-bound buttons** (`docs/features/roles/promote.md`, `demote.md`, `roles.md`, `docs/features/misc-modules.md`): the callback tables show the opener-carrying shapes and the rule that only the opener can act or cancel. Behavior changes: none, docs only.

- **Speedtest and greeting notes match the code** (`docs/features/misc-modules.md`): the speedtest section names the archived upstream and its pin, and the greeting section states the live connection read. Behavior changes: none, docs only.

- **Guides follow the consolidated layout** (`.agents/rules/`, `AGENTS.md`, `CONTRIBUTING.md`, `docs/architecture/`, `docs/features/`, `docs/README.md`): workflow paths, code rules, architecture maps, and feature guides now point at `pipelines/`, `tcbot/__init__.py`, `tcbot/__main__.py`, and `error_reporter.py`. Behavior changes: none, docs only.

- **Published release notes live per version** (`CHANGELOG.md`, `docs/releases/`, `docs/README.md`, `AGENTS.md`): each published release moved unchanged into `docs/releases/vX.Y.Z.md` dated with its release date, and the changelog root now keeps only the `Unreleased` section and a linked release index. Behavior changes: none, docs only.

- **Validation pointers follow the surviving sources** (`AGENTS.md`, `.agents/rules/`, `docs/architecture/repository-map.md`): rule headers now name `docs/operations/ci-cd.md` for checks and `AGENTS.md` for read and update discipline, and the repository map lists the six remaining rule files. Behavior changes: none, docs only.

- **Driver and path references match the tree** (`.agents/rules/docs-sync.md`, `.agents/rules/asyncio-gather-rules.md`, `tcbot/__init__.py`, `tcbot/serverless.py`, `tcbot/database/mongos.py`, `tcbot/database/scheduler.py`, `docs/features/moderation/warnings.md`, `docs/features/moderation/check.md`): the synchronous PyMongo `db_call` model and the single-file database paths replace the retired driver and package-form paths. Behavior changes: none, docs and comments only.

</details>


## Releases

### v6.x

- [6.9.0](docs/releases/v6.9.0.md)
- [6.8.0](docs/releases/v6.8.0.md)
- [6.7.0](docs/releases/v6.7.0.md)
- [6.6.1](docs/releases/v6.6.1.md)
- [6.6.0](docs/releases/v6.6.0.md)
- [6.5.1](docs/releases/v6.5.1.md)
- [6.5.0](docs/releases/v6.5.0.md)
- [6.4.0](docs/releases/v6.4.0.md)
- [6.3.0](docs/releases/v6.3.0.md)
- [6.2.0](docs/releases/v6.2.0.md)
