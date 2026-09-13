# Changelog

For workflow details mentioned below, see [`docs/operations/ci-cd.md`](docs/operations/ci-cd.md). For project overview, see [`README.md`](README.md). For contributor rules, see [`CONTRIBUTING.md`](CONTRIBUTING.md). For AI Agents see [`AGENTS.md`](AGENTS.md). For AI agent knowledge see [`docs/README.md`](docs/README.md).

## [Unreleased]

<details open>
<summary>Unreleased changes (click to collapse)</summary>

### Added

- **Every user-facing message follows the message language** (all `i18n/en-US/*.toml`, every command module, every conversation flow, `tests/test_i18n.py`, `i18n/README.md`, `docs/features/language.md`): moderation replies and alerts, reason and proof prompts, ban/kick/mute/warn/unban executors with their summaries and result cards, appeal submission and staff review, connect flow, check profiles and drill-downs, stats views, promotion and demotion, start/about/privacy/additional menus, join and leave notices, identity refusals and recognition notes, and all button labels. Private chats read the sender's locale, groups read the group locale, direct messages read the recipient's locale. Help topics, overviews, sections, and keyboards rebuild per request. Audit-log posts, staff operational messages, and error reports stay English. Output identical for the default locale.

- **Shared reply texts follow the message language** (`i18n/en-US/common.toml`, `tcbot/modules/helper/replies.py`, 20 command and flow modules, `tests/test_i18n.py`): every shared notice (target errors, role and permission refusals, rate-limit waits, default reason, all five rank tiers) now loads from one catalog file in the render locale. Each call site states its send path, so plain alerts and formatted messages each render correctly. Help and message wording is identical for the default locale.

- **Runtime i18n begins: per-update locale plus netspeed** (`tcbot/modules/helper/locale.py`, `tcbot/modules/language.py`, `netspeed.py`, `i18n/en-US/netspeed.toml`, `tests/test_i18n.py`, `i18n/README.md`): handlers resolve the render locale once via `locale_for_update` (private chats use the sender's locale, groups use the group locale). Ping and speedtest replies, prompts, and result lines now load from TOML; plain sends render verbatim, MarkdownV2 sends render escaped. Output identical for the default locale.

- **All module help migrated to TOML** (`i18n/en-US/*.toml`, every module help block, `tests/test_i18n.py`, `i18n/README.md`): every `/help` topic now loads its prose from one catalog file per module, so translators work without touching code. Section order, labels, and shared constants stay in Python. Help output is identical for all modules.

- **Per-user and per-group language preferences** (`i18n/en-US/common.toml`, `button.toml`, `language.toml`, `i18n/README.md`, `tcbot/utils/i18n.py`, `tcbot/database/settings_db.py`, `groups_db.py`, `documents.py`, `mongos.py`, `tcbot/modules/language.py`, `helper/keyboards.py`, `tests/test_i18n.py`, `docs/features/language.md`): `/language` (`/lang`, `/langs`) and a start-menu `Language` button share one selection flow for personal or group locale. Personal choices live in a dedicated `user_settings` collection; group choices live on the group row. Group changes need owner or staff rank. Translations ship as one TOML file per domain with fallback to `en-US`.

### Changed

- **Clearer bot wording across every message** (`i18n/en-US/*.toml`, `tests/test_i18n.py`): error replies now say what happened and what to do next instead of naming server internals, the rate-limit wait renders correctly at one second, the connect confirmation names the group, and stale or clumsy lines (group-chat mute note, kick-unban hint, transfer result, empty-page notices) read plainly. Button labels and help structure unchanged; every template still renders clean.

- **Cleaner engine comments and finished locale threading** (`tcbot/utils/i18n.py`, `helper/workflows/ban_flow.py`, `reason_flow.py`): the catalog loader example names the real domain file, the code-span renderer uses plain backslash literals, and two completed locale-threading reminders are gone since the ban flow already carries its locale. The reason parser docstring now describes the verified-override path. No behavior change.

- **Agent rules reorganized for translation work** (`.agents/rules/`): `docs-rules.md` is now `docs-sync.md` and `tooling-validation.md` is now `tooling-skills-use.md`, with every cross-reference updated across rules, skills, guides, and the repository map. New `changelog-style.md` pins the release-note voice: short reader-first bullets, no tool names, no process narration, no implementation jargon. The task workflow, docs workflow, and boot prompt now point at it so new entries follow it from the start. Comment rules gain localized-code guidance (explain the locale choice, keep translator notes in TOML). Skill use now means loading the skill and reading all of its instructions, including commit.

- **Agent rules now cover internationalization** (`.agents/rules/code-style.md`, `tooling-skills-use.md`, `docs-sync.md`, `CONTRIBUTING.md`): new i18n section with locale resolution and threading, template and placeholder contracts, render-mode matching, per-locale help, and button-label ownership; stale English-only message claims corrected; validation table and pre-edit checklist gain the i18n row; docs rules index the translation catalog and language guide.

- **Help menus standardized across modules** (`tcbot/modules/warnings.py`, `muting.py`, `groups.py`, `connecting.py`, `syncing.py`, `netspeed.py`, `maintenance.py`, `stats.py`, `language.py`, `kicking.py`, `banning.py`, `disconnecting.py`, `appeals.py`, `admins.py`): every overview is verb-led, labels and example shapes are uniform, and each `Who can use` line names the exact rank. Warn-limit wording renders from configuration.

</details>

## [6.7.0] - 2026-09-12

<details>
<summary>6.7.0 changes (click to expand)</summary>

### Changed

- **MarkdownV2 follow-up polish** (`tcbot/modules/helper/decorators.py`, `maintenance.py`, `parse_logmsg.py`): `decorators.py` now uses modern generics like `cache.py`, with the duplicated import block merged. Two awkward comments reworded; two `parse_logmsg` docstrings no longer reference `<code>` tags.

- **Full MarkdownV2 message migration** (`tcbot/utils/formatter.py`, `time_and_date.py`, `error_reporter.py`, every `tcbot/modules/` sender, `parse_logmsg.py`, `identity.py`, `replies.py`, all help/about/privacy content, `tests/test_formatter.py`, `test_time_and_date.py`, rules/skills/docs): every Telegram message now renders with `parse_mode="MarkdownV2"`; legacy `Markdown` and leftover `HTML` modes are gone. `formatter.py` owns the 19-char escape set (including the backslash the rewrite had dropped), helpers escape internally, and static text is escaped at definition. Timestamps arrive pre-escaped from the single clock source. `safe_reply`/`safe_edit`/`safe_edit_cb` default to MarkdownV2. Broadcast keeps its V2-then-plain fallback with corrected help copy. Fixed along the way: unclosed parens in auto-ban lines, double-escaped promo display text, a pre-escaped name in a plain reply, and unescaped reason-flow paths.

- **License changed to SSPL 1.0** (`LICENSE`, `README.md`): proprietary all-rights-reserved terms replaced with the Server Side Public License, Version 1. Copyright holders unchanged.

- **Database hot-path hardening and precise typing** (`tcbot/database/bans_db.py`, `users_cache.py`, `groups_db.py`, `redis_client.py`, `mongos.py`, `users_roles.py`, `tcbot/modules/helper/workflows/check_flow.py`): page-size clamping happens once, batch mentions skip repeat IDs, group-title refresh is one atomic update, Redis reconnects close the old pool first, `role_meta` returns a precise type, and a stale DNS docstring is fixed. No new indexes.

### Documentation

- **MarkdownV2 contract sync** (`PROMPT.md`, `AGENTS.md`, `CONTRIBUTING.md`, `.agents/rules/code-style.md`, `asyncio-gather-rules.md`, `.agents/skills/feature-reviewer/SKILL.md`, `docs/README.md`, `docs/architecture/helpers.md`, `utilities.md`, `modules.md`, `repository-map.md`, `docs/features/moderation/groups.md`, `disconnecting.md`, `unbanning.md`): every parse-mode reference now states MarkdownV2, formatter tables show V2 markers, and the groups render example matches the code.

- **Agent contract alignment for scale and honesty** (`AGENTS.md`, `PROMPT.md`): the overview now states the large-scale framing, with two new working rules: evaluate blast radius on every moderation finding, and never disguise a behavior change as cleanup.

</details>

## [6.6.1] - 2026-09-11

<details>
<summary>6.6.1 changes (click to expand)</summary>

### Changed

- **Shared back-button factory for drill-down error cards** (`tcbot/modules/helper/workflows/stats_flow.py`, `check_flow.py`, `tcbot/modules/helper/keyboards.py`): eleven inline back buttons on stats/check not-found cards now use `keyboards.back_to_module_kb`. Labels, callbacks, and styles identical.

- **Shared interruption guard plus one-call replies** (`tcbot/utils/dispatch.py`, `tcbot/modules/helper/parse_editmsg.py`, 21 command/workflow modules, `docs/architecture/utilities.md`, `helpers.md`): one shared guard owns the stop-on-interruption pattern at every parallel site, and `safe_reply` replaces the repeated try/reply/log blocks. Fixed along the way: a crash-prone `uid` on the appeal double-fault path and a misordered import.

- **Database deduplication and modern typing** (`tcbot/database/users_cache.py`, `warns_db.py`, `mutes_db.py`, `mongos.py`, `scheduler.py`, `cache.py`): duplicated fetch closures, warn-recount fallbacks, and warn-clear paths each share one owner; five untyped workarounds removed. No new indexes.

</details>

## [6.6.0] - 2026-09-11

<details>
<summary>6.6.0 changes (click to expand)</summary>

### Changed

- **`/tcsync` enforcement reconciliation plus optional scheduled sweep** (`tcbot/modules/syncing.py`, `tcbot/database/scheduler.py`, `tcbot/__init__.py`, `tcbot/__main__.py`, `config.env.example`, `AGENTS.md`, `docs/features/moderation/sync.md`, `docs/architecture/database.md`, `tests/test_syncing.py`): new `mod_only` `/tcsync` re-drives missed enforcement, bounded per run. Bare runs sweep active bans; targeted runs verify one user both directions. Present-but-unkicked users are enforced; absent and privileged users are skipped, never failures. `SYNC_INTERVAL_HOURS` (default 0, disabled) registers a log-only interval job. Sync runs never create, modify, or deactivate ban records.

- **Unban reply names missed groups** (`tcbot/modules/helper/workflows/unban_flow.py`, `docs/features/moderation/unbanning.md`): the summary now lists up to 5 transient-failed groups, so operators know exactly which chats still need a re-drive. Counts and log behavior unchanged.

- **Join pipeline plus replay stages consolidated** (`tcbot/modules/greeting.py`, `tcbot/modules/helper/workflows/connected_flow.py`): four identical lookup-plus-demote blocks share one helper, three identical gates share another, and the connect replay runs as explicit ban/mute stages. Replies, ordering, and refusal paths identical.

- **Target resolution split into testable stages** (`tcbot/modules/helper/extraction.py`, `tests/test_extraction.py`): the reply/args/entity chain is now three small functions with identical priority. A miss-masked-as-hit found during the split is fixed.

- **Unbounded ban-list helper removed, precise warn ID typing** (`tcbot/database/bans_db.py`, `mongos.py`, `documents.py`, `docs/architecture/database.md`): the zero-caller full-scan `active_bans()` is removed; `WarnDoc._id` is now `ObjectId`.

- **Automated checks with 82 fast cases** (`tests/`, `pyproject.toml`): new checks covering parsing, keyboards, identity copy, appeal gates, pagination, clock, fan-out, deep links, extraction, and sync classification. Runs in under a second without extra dependencies. No production code changed.

- **Shared paginated drill-down keyboard** (`tcbot/modules/helper/keyboards.py`, `stats_flow.py`, `check_flow.py`, `tests/test_drill_kb.py`, `docs/reference/keyboard-styles.md`): one `paged_drill_kb` owns the numbered grid, nav row, and back button for stats and check lists. Layout pinned by automated checks.

- **Appeal flow split into submit and review modules** (`tcbot/modules/helper/workflows/appeal_submit_flow.py`, `appeal_review_flow.py`, `appeal_flow.py`, `keyboards.py`, `docs/architecture/workflows.md`, `docs/features/appeals.md`): `BuildAppeal` is now a thin facade over submit and review mixins; both keyboards moved into `keyboards.py`. Imports, callbacks, replies, and ordering unchanged.

- **Promotion enqueue survives random-ID collision** (`tcbot/database/queues_db.py`, `docs/architecture/database.md`): `enqueue` retries once with a fresh ID on collision; a second failure still propagates so real duplicates report correctly. One extra insert attempt only on failure.

- **L2 cache write can no longer fail the fetch** (`tcbot/database/cache.py`, `docs/architecture/database.md`): a payload-encode failure now degrades to L1-only instead of raising after the value was already served.

- **Prefix matching slimmed down, results identical** (`tcbot/utils/prefixes.py`): two subsumed gates and one unreachable check removed; the bot-username lookup runs only when the text contains `@`. Matching confirmed identical across an exhaustive old-vs-new comparison. Command matching is unchanged.

- **Absolute full-read rule** (`.agents/rules/tooling-validation.md`): the read-before-work rule now forbids partial reads outright, so every edit is made against full surrounding context.

- **Removed stale `.roo` and `.trae` symlinks** (`pyproject.toml`): symlinks and their dead lint excludes deleted. `.agents` untouched.

- **Single formatter source, helper shim removed** (36 files under `tcbot/modules/`, `tcbot/utils/formatter.py`, `docs/architecture/helpers.md`, `utilities.md`, `repository-map.md`, `AGENTS.md`, `.agents/rules/code-style.md`, `docs-rules.md`): every import now comes from `tcbot.utils.formatter` directly; the re-export shim is deleted. No function changed.

- **Staff global throttle tier plus honest retry countdown** (`tcbot/modules/helper/decorators.py`, `replies.py`, `docs/architecture/helpers.md`): Founder skips the global bucket; Tester and above share a roomier staff bucket; everyone else keeps the existing quota. Failed lookups land on the strict bucket. Waits clamp to a minimum of 1 second. Staff throttle at the 17th call, regulars at the 9th, Founder unlimited.

- **Deterministic module loading plus precise loader typing** (`tcbot/modules/__init__.py`, `docs/architecture/modules.md`, `repository-map.md`): discovery is sorted so startup order is stable; registry and handler types are explicit; one unreachable branch removed.

- **Built-in community link defaults** (`tcbot/__init__.py`, `config.env.example`, `docs/getting-started/setup.md`, `README.md`, `AGENTS.md`): the five community URLs fall back to built-in defaults when unset, so the links menu shows all five buttons with zero setup. A set env value still wins.

- **Identity classify hardening plus exemption staleness guard** (`tcbot/modules/helper/identity.py`, `decorators.py`, `docs/architecture/helpers.md`): interrupted lookups now stop instead of degrading into a fallback identity, and the exemption path documents why no sync fast path exists. Lookup-failure behavior unchanged.

- **Smarter rate limits plus privacy copy that matches the code** (`tcbot/modules/helper/decorators.py`, `replies.py`, `tcbot/modules/privacy.py`, `docs/architecture/helpers.md`): four `Slow down` variants share one helper; the Founder bypasses quotas via the cached owner ID, and outages still refuse safely. Privacy texts now describe actual handling: records lookable-up via `/check`, promotion requests listed, real retention mechanisms named. Quotas unchanged.

- **Semantic button colors plus tidier rows** (`tcbot/modules/helper/keyboards.py`, `appeal_flow.py`, `connected_flow.py`, `reason_flow.py`, `proof_flow.py`, `stats_flow.py`, `docs/reference/keyboard-styles.md`, `docs/architecture/helpers.md`): Approve is green, Reject and destructive Confirm are red, continue/select steps are blue; Cancel, Back, and nav stay neutral. Older clients render the same buttons without color. No logic or callback change.

- **Start-menu buttons in PRIMARY blue** (`tcbot/modules/helper/keyboards.py`, `docs/reference/keyboard-styles.md`): every start-menu option carries PRIMARY; only Back and Cancel stay neutral. Labels, rows, and callbacks unchanged.

- **PRIMARY for all remaining actionable buttons** (`tcbot/modules/helper/keyboards.py`, `stats_flow.py`, `check_flow.py`): stats menus, drill-ins, search, check drill-ins, warn buttons, and info URL buttons now carry PRIMARY. Only Cancel, Back, and Prev/Next stay neutral. Labels, rows, and callbacks unchanged.

- **Shared appeal gates plus parallel reject writes** (`tcbot/modules/helper/workflows/appeal_flow.py`): triplicated stale-review, cooldown, and state-clear blocks share one helper each; rejection resolves the name in parallel with the cooldown write.

### Fixed

- **Typed IDs now beat quoted messages in target resolution** (`tcbot/modules/helper/extraction.py`, `banning.py`, `kicking.py`, `muting.py`, `warnings.py`, `checking.py`, `tests/test_extraction.py`, `docs/features/moderation/banning.md`, `kicking.md`, `muting.md`, `warnings.md`, `check.md`, `docs/architecture/helpers.md`, `workflows.md`): a numeric ID or `@username` that verifies as a real user different from the quoted sender is now treated as the target instead of being silently swallowed as reason text, so reply-plus-ID commands act on the person named. Unverified tokens (reasons starting with a number, unknown IDs) and partial-name matches keep the reply target, and groups or channels can never hijack it. The ban, kick, mute, and warn entries share one resolver that also reports whether the first token was consumed, keeping reasons clean. `/check` prefers any resolving argument since it is read-only. Behavior changes: reply + verified ID targets the ID, not the quote.

- **Re-ban confirmation card plus in-place prompt edits** (`tcbot/modules/banning.py`, `helper/workflows/ban_flow.py`, `helper/keyboards.py`, `helper/parse_editmsg.py`, `tests/test_keyboards.py`, `docs/features/moderation/banning.md`, `docs/architecture/workflows.md`, `docs/reference/keyboard-styles.md`): re-banning an active ban now shows a confirmation card (existing ID, old and new reasons) instead of flowing straight to proof collection. Demotion moved after confirmation so Cancel never demotes without banning. Cancel and timeout edit the prompt in place and strip dead buttons. Behavior changes: re-bans require Continue; no more live buttons left behind.

- **Multi-item proof: GIF/file support plus Done collection mode** (`tcbot/modules/helper/workflows/proof_flow.py`, `ban_flow.py`, `reason_flow.py`, `banning.py`, `tcbot/__init__.py`, `config.env.example`, `README.md`, `docs/getting-started/setup.md`, `docs/features/moderation/banning.md`, `kicking.md`, `muting.md`, `warnings.md`, `docs/features/workflow-overview.md`, `docs/architecture/workflows.md`, `docs/reference/keyboard-styles.md`): proof now accepts photos, videos, GIFs, and files through one shared filter. Collection is Done-driven with a silence window (default 4 s, was 2) and a 60 s cap. Empty Done answers with a retry alert. Behavior changes: every proof execution waits for Done or the window; GIF/file proof is new.

- **Restated target ID dropped from reply-path reasons** (`tcbot/modules/helper/workflows/reason_flow.py`, `banning.py`, `kicking.py`, `muting.py`, `warnings.py`, `docs/features/moderation/banning.md`, `kicking.md`, `muting.md`, `warnings.md`, `docs/architecture/workflows.md`): reply plus an explicit ID no longer stores the ID twice in the reason. Only the intended case changed.

- **PR-creation failures now name the repository toggle** (`.github/workflows/dependency-update.yml`, `auto-fix.yml`, `docs/operations/ci-cd.md`): the step emits the exact Settings fix instead of leaving only the raw GraphQL error. Still exits non-zero; re-running recovers.

- **Warn auto-ban retries after total enforcement failure plus actionable appeal card on DB failure** (`tcbot/modules/helper/workflows/warning_flow.py`, `appeal_review_flow.py`, `docs/features/moderation/warnings.md`, `docs/features/appeals.md`, `docs/getting-started/setup.md`, `README.md`): the trigger is now `>=` so a fully-failed fan-out retries on the next warn instead of wedging. Appeal approval on DB failure now answers with a retry alert and leaves the card actionable. Docs updated.

- **Interrupted operations stop cleanly across helpers** (`tcbot/utils/dispatch.py`, `tcbot/database/cache.py`, `groups_db.py`, `warns_db.py`, `scheduler.py`, `users_roles.py`, `ban_flow.py`, `unban_flow.py`, `tests/test_dispatch.py`, `docs/architecture/utilities.md`): `fan_out`, the Redis chain, group migrations, warn paths, the expiry job, and ban/unban pre-commit gathers now stop on interruption instead of recording it as failure data. Finished notifications still send best-effort.

- **Kick refused up front in private chats** (`tcbot/modules/kicking.py`, `tests/test_kick_guard.py`): `/tckick` in bot PM now replies `Use this command in a group.` instead of running the full pipeline into a Telegram error.

- **Speedtest share photo no longer dropped** (`tcbot/modules/netspeed.py`, `tests/test_netspeed.py`): the gate accepts both `http://` and `https://` share URLs, since the library builds plain-http links. Only non-http(s) values fall back to text.

- **Benign demote-DM failures no longer page LOG_ERRORS** (`tcbot/modules/helper/workflows/demote_flow.py`, `tests/test_demote_notify.py`): blocked-bot and deleted-account refusals go info-level; log-channel failures stay error-level. Return behavior unchanged.

- **Redis pool lifecycle plus scheduler stop hygiene** (`tcbot/database/redis_client.py`, `scheduler.py`): the pool is now disconnected explicitly on close and failed PING; `scheduler.stop()` cancels an outliving background task.

- **Kick edits the prompt instead of double-messaging** (`tcbot/modules/kicking.py`, `tcbot/modules/helper/workflows/kicking_flow.py`, `tests/test_kick_summary.py`, `docs/features/moderation/kicking.md`, `docs/architecture/workflows.md`): the summary now edits the proof prompt in place, falling back to a reply only when the prompt is gone. User-visible text unchanged.

- **Identity recognition on every command surface** (`tcbot/modules/checking.py`, `tcbot/modules/helper/workflows/check_flow.py`, `tcbot/modules/helper/identity.py`, `docs/features/moderation/check.md`): all 29 handlers checked. Two gaps closed: check profiles note Telegram and anonymous-admin targets, and `/checkme` from a bot/anonymous sender is refused instead of reporting a misleading clean verdict.

- **`/check` recognizes the bot itself and the viewer** (`tcbot/modules/helper/workflows/check_flow.py`, `tcbot/modules/checking.py`, `docs/features/moderation/check.md`, `docs/architecture/workflows.md`, `docs/features/moderation/banning.md`): bot and self targets get recognition notes; Founder/staff keep the role label. Counts and keyboards identical; failed lookups degrade to no note.

- **Runner shutdown waits for graceful exit** (`.github/workflows/run-bot.yml`, `docs/operations/ci-cd.md`): the bot is backgrounded directly so shutdown can poll up to 60 s for exit before scrub/upload steps. Supervision, fail-fast, backoff, and cron fallback unchanged.

- **CI dummy tokens match required shape** (`.github/workflows/lint.yml`, `dependency-update.yml`): dummy tokens padded to full shape so CI runs stop logging a spurious warning.

- **Interrupted appeal reads leave the review card intact** (`tcbot/modules/helper/workflows/appeal_flow.py`): interruption now stops with the card untouched, so a re-tap retries cleanly. Finished notifications still send best-effort.

### Documentation

- **Human-first contribution guide plus agent-routing rules** (`CONTRIBUTING.md`, `AGENTS.md`, `PROMPT.md`, `CLAUDE.md`): `CONTRIBUTING.md` is rewritten for human contributors instead of routing developers through agent rule files; AI agents must complete the rules checkpoint before touching code. `AGENTS.md` gains the audience split and the release version-bump rule; `PROMPT.md` cross-links both.

- **Orphaned sync doc indexed plus transport utility documented** (`docs/README.md`, `docs/architecture/modules.md`, `repository-map.md`, `utilities.md`, `README.md`, `docs/getting-started/setup.md`, `AGENTS.md`): the sync guide is now linked from the docs index, module table, and README command table. New transport section in utilities; interval setting documented in README and setup. One em-dash removed per the style rule.

- **Database doc sync** (`docs/architecture/database.md`): pool ownership, scheduler stop behavior, enqueue retry, and L1-only degradation rows added.

- **Appeal doc sync** (`docs/features/appeals.md`, `docs/architecture/workflows.md`): duplicated approval sentence removed; rejection ordering, interruption behavior, and shared-gate rows documented.

- **GitHub Actions automation tutorial** (`README.md`): new collapsible Deployment block covering all four CI workflows. Points at the full operations reference. No code change.

- **Collapsible deployment tutorials** (`README.md`, `docs/getting-started/setup.md`): one tutorial per target (Actions runner, Vercel, Docker, Heroku, VPS, Windows). No code change.

</details>

## [6.5.1] - 2026-09-07

<details>
<summary>6.5.1 changes (click to expand)</summary>

### Changed

- **`/tcstats` Users pane is Owner/Founder only** (`tcbot/modules/helper/workflows/stats_flow.py`, `tcbot/modules/stats.py`, `docs/features/statistics.md`): the Users button and its callbacks now require Owner/Founder, with a Founder-only alert and a retry alert on outage. Previously anyone was one tap from the full user list. Nothing else changed.

- **Shared appeal button plus one-per-row ban-log URLs** (`tcbot/modules/helper/keyboards.py`, `tcbot/modules/helper/workflows/ban_flow.py`, `docs/architecture/helpers.md`): one keyboard owner for the Submit Appeal button; proof/appeal links stack one per row so ID labels stop truncating on narrow clients. Same buttons, URLs, and callbacks.

- **Shared proof/reason hardening** (`tcbot/modules/helper/extraction.py`, `reason_flow.py`, `proof_flow.py`, `warning_flow.py`, `kicking_flow.py`, `muting_flow.py`, `banning.py`, `kicking.py`, `muting.py`, `warnings.py`, `docs/architecture/helpers.md`, `workflows.md`, `docs/features/moderation/banning.md`, `kicking.md`, `muting.md`, `warnings.md`): four reply-shape checks share one helper; inline reasons share the 1000-char cap with fail-fast replies; write-only proof plumbing removed. Overlong inline reasons now get the retry notice like typed reasons.

- **Shared promote/demote resolve helpers** (`tcbot/modules/admins.py`): executor/target fetch, classify/role load, and the callback staff check each share one helper. Repeated checks cost no database reads on cache hits.

- **Concurrent proof uploads on kick/mute/warn executors plus shared pre-fan-out re-demote** (`tcbot/modules/helper/workflows/demote_flow.py`, `kicking_flow.py`, `muting_flow.py`, `warning_flow.py`): the proof upload no longer blocks enforcement serially; triplicated re-demote blocks share one helper. Failure replies unchanged.

- **Help menu modernization** (`tcbot/modules/help.py`, `docs/architecture/modules.md`): the prefix footer is precomputed once; topic lists are explicit copies. No text, callback, or navigation change.

- **Consistency sweep in serverless, health, and error paths** (`tcbot/serverless.py`, `tcbot/alive.py`, `tcbot/database/mongos.py`, `tcbot/utils/circuit_breaker.py`, `tcbot/utils/error_reporter.py`): dead shadow constants removed; health checks compare enum members; modern generics; single-pass expiry sweeps.

- **Handler entry hardening sweep** (`tcbot/__init__.py`, `tcbot/modules/connecting.py`, `disconnecting.py`, `broadcasting.py`, `greeting.py`, `admins.py`, `banning.py`, `kicking.py`, `muting.py`, `stats.py`): entry asserts became guard returns (asserts vanish under `python -O`); tuple-excepts split per convention.

- **Health mongodb field follows the live circuit** (`tcbot/alive.py`): the field now reflects the live breaker state instead of a sticky startup flag.

- **Owner DMs throttled per incident** (`tcbot/utils/error_reporter.py`): repeats of one incident past 3/hour are suppressed; each new incident still notifies.

- **Active-mute TTL pruning** (`tcbot/database/mongos.py`, `tcbot/database/documents.py`, `docs/architecture/database.md`): expired timed mutes are now auto-deleted by a TTL index; permanent mutes never expire. Only rows the queries already ignore are pruned.

- **Warn-counter repair failures escalated to error** (`tcbot/database/warns_db.py`): counter-delete failures now ship to `LOGS_ERRORS`, since a surviving counter corrupts later threshold math.

- **No-em-dash rule** (`.agents/rules/comment-style.md`, `.agents/rules/code-style.md`): U+2014 forbidden in every tracked file, documented in `comment-style.md`. All 20 existing occurrences swept.

- **Shared auto-demote-or-abort helper** (`tcbot/modules/helper/workflows/demote_flow.py`, `tcbot/modules/banning.py`, `kicking.py`, `muting.py`): three triplicated demote-fail blocks share one owner. Reply text and refusal flow identical.

- **Demote failure visibility** (`tcbot/modules/helper/workflows/demote_flow.py`): log/DM failures after role removal now log at error level. The removal itself is unaffected.

- **Broadcast replies via safe_reply** (`tcbot/modules/broadcasting.py`): three one-shot replies use the shared helper with identical text.

- **Classify caller contract** (`tcbot/modules/helper/identity.py`): the pairing rule is now documented explicitly. All call sites checked.

- **Read-tool rule wording** (`.agents/rules/tooling-validation.md`): the rule now covers all shell search tools, which must not substitute for full reads.

- **Ave Studio renamed to Ave Labs**: copyright holder renamed across headers, license, README, and style guide.

- **Cached auth reads** (`tcbot/database/users_roles.py`, `tcbot/modules/helper/decorators.py`): owner and staff checks resolve from cache (300 s / 60 s TTL) instead of uncached reads. Rank semantics unchanged.

- **Bounded Redis latency** (`tcbot/database/cache.py`, `tcbot/modules/helper/decorators.py`): cache GET and rate-limiter calls time out and fall through to local behavior. A stalled Redis no longer holds commands. These are bounds only; speed still depends on workload.

- **Parallel identity sweep for unknown users** (`tcbot/modules/helper/extraction.py`): connected groups are probed concurrently with an overall deadline; first hit wins. Per-probe failures stay debug-level.

- **Stable-ID ban detail without full-list rescan** (`tcbot/modules/helper/workflows/stats_flow.py`): detail views with a stable ID fetch the record directly; legacy buttons keep the old lookup.

- **Bounded batch-join handling** (`tcbot/modules/greeting.py`): invite-link batches process in bounded batches instead of unlimited parallel sends. Per-member failures stay isolated.

- **Shared group-list outage reply** (`tcbot/modules/helper/replies.py`, `broadcasting.py`, `maintenance.py`, `groups.py`): three inline copies of the retry text share one constant. No text change.

- **Dead identity resolver removed, fan-out counting docs corrected** (`tcbot/modules/helper/extraction.py`, `docs/architecture/helpers.md`, `docs/architecture/database.md`, `docs/architecture/utilities.md`): zero-caller resolver removed; docs now name the correct failure counters.

- **Modern typing and warning hygiene** (`tcbot/serverless.py`, `tcbot/utils/pagination.py`, `tcbot/alive.py`, `tcbot/modules/netspeed.py`): generic types modernized, webhook path no longer leaks coroutines, one shared speedtest failure responder.

### Documentation

- **Role doc sync for promote/demote hardening** (`docs/features/roles/promote.md`, `roles.md`, `demote.md`): approval-path cleanup, transfer order, and helper contracts documented to match the code.

- **Concurrent-upload and re-demote doc sync** (`docs/architecture/workflows.md`, `docs/features/moderation/kicking.md`, `muting.md`, `warnings.md`, `docs/features/roles/demote.md`): guides now describe concurrent proof upload and the shared re-demote API; stale claims corrected.

- **Ban doc sync** (`docs/features/moderation/banning.md`, `docs/features/workflow-overview.md`, `docs/architecture/workflows.md`, `docs/features/moderation/unbanning.md`): diagrams now show store-plus-log before fan-out; reply-reason rule and refusal path documented; stale line ranges dropped.

- **README rewrite** (`README.md`): replaced the generated-sounding long form with a concise engineer-facing version: value proposition, quick start, six feature bullets, required-only config table, run/deploy/health sections, validation block, and six curated doc links.

- **Warns help staff note** (`tcbot/modules/warnings.py`): `/tcwarn` help now states that staff targets are demoted first and exempted from the auto-ban.

- **Doc sync, round 4** (`docs/features/moderation/warnings.md`, `kicking.md`, `docs/features/roles/roles.md`, `docs/architecture/database.md`, `workflows.md`, `helpers.md`, `docs/features/workflow-overview.md`, `tcbot/modules/warnings.py`, `unbanning.py`, `muting.py`, `helper/identity.py`): access claims, auto-ban scope, index tables, executor signatures, and help texts corrected to match the code.

- **Run commands use the `uv run` prefix, round 2** (`AGENTS.md`, `CONTRIBUTING.md`, `PROMPT.md`, `README.md`, `replit.md`, `docs/README.md`, `docs/getting-started/setup.md`, `docs/operations/backup-and-restore.md`, `docs/operations/ci-cd.md`, `docs/architecture/repository-map.md`, `.agents/skills/feature-reviewer/SKILL.md`): every remaining bare run command now uses the `uv run` prefix. CI descriptions match the actual workflow steps.

- **Repo activity badge** (`README.md`): Repobeats analytics image added under a new `Repo activity` section.

- **Run commands use the `uv run` prefix** (`README.md`, `.agents/rules/tooling-validation.md`, `.agents/rules/docs-rules.md`): run, lint, and type-check commands now use the `uv run` prefix, matching the Replit entrypoint.

- **Appeal doc sync** (`docs/features/appeals.md`, `docs/features/moderation/unbanning.md`, `docs/features/workflow-overview.md`, `docs/architecture/workflows.md`, `docs/architecture/database.md`): submit revalidation, atomic review claim, retry behavior, and reject ordering documented; stale reuse claims removed.

- **Kick/mute/warn doc sync** (`docs/features/moderation/kicking.md`, `muting.md`, `warnings.md`, `docs/architecture/workflows.md`, `helpers.md`, `database.md`): reply-target reason preservation, persist-first mute order, and warn raise contracts documented; stale line ranges dropped.

- **Response-path doc sync** (`docs/features/moderation/connecting.md`, `docs/architecture/helpers.md`): connect progress edit and numeric-ID cache shortcut documented.

- **Doc sync, round 5** (`docs/operations/ci-cd.md`, `docs/features/moderation/muting.md`, `connecting.md`, `README.md`, `replit.md`, `docs/getting-started/setup.md`, `AGENTS.md`): dead anchors, stale line refs, and missing setup rows fixed.

### Fixed

- **Promotion approval clears stale subroles** (`tcbot/modules/admins.py`): approval now removes leftover Developer/Tester rows like the direct path already does, so demote can no longer resurrect them. Failures only log since the promotion already committed. Docs updated.

- **Interrupted role and queue operations stop cleanly** (`tcbot/modules/admins.py`, `tcbot/modules/helper/workflows/promote_flow.py`): interrupted reads no longer turn into fallback names or verdicts; interrupted answers are no longer swallowed.

- **Precise `BanDoc` typing for ban-detail rendering** (`tcbot/modules/helper/ban_info.py`, `checking.py`, `helper/workflows/check_flow.py`, `stats_flow.py`): detail builders take `BanDoc` with safe access; all casts removed. Sparse records render fallbacks instead of raising.

- **Broadcast plaintext retry only on parse failures** (`tcbot/modules/broadcasting.py`): non-parse errors now count straight as failures instead of paying a retry that could only fail again. Totals unchanged.

- **Scheduler jobstore shares the certifi TLS pinning** (`tcbot/database/mongos.py`, `tcbot/database/scheduler.py`): one shared helper pins both the Motor client and the scheduler's client. Explicit URI overrides still win.

- **Speedtest trusts the certifi bundle instead of the system CA store** (`tcbot/modules/netspeed.py`): a small subclass points the opener at certifi, covering all stages. No change where the system store works.

- **Runner log artifacts scrubbed of credentials** (`.github/workflows/run-bot.yml`, `docs/operations/ci-cd.md`): token- and URI-auth-shaped substrings are stripped before artifacts ship or tails print. Excerpts remain for debugging.

- **Unmute/unban answer group-fetch and executor outages** (`tcbot/modules/helper/workflows/muting_flow.py`, `tcbot/modules/unbanning.py`, `docs/features/moderation/muting.md`, `unbanning.md`): unguarded awaits now reply with a retry notice and leave state untouched.

- **Leaveall/cleanup answer group-list outages** (`tcbot/modules/maintenance.py`): both commands now reply with a retry notice; rows without IDs count as failed instead of raising.

- **Unban log renders the deactivated ban ID** (`tcbot/modules/helper/parse_logmsg.py`): the audit entry now carries the `Ban ID` field like the other logs. The dead `update_count` parameter is removed.

- **Ban aborts safely on database write failure** (`tcbot/modules/helper/workflows/ban_flow.py`): write failures now abort before any group is touched, with a retry notice on the prompt. No more appeal links for records that do not exist.

- **Ban reply reason keeps leading ID-like tokens** (`tcbot/modules/banning.py`): reply-target commands treat every argument as reason text, mirroring target resolution. Entry asserts became guard returns.

- **Ban executor cleanup** (`tcbot/modules/helper/workflows/ban_flow.py`): a dead pre-fetched name task removed; the final edit result is logged.

- **Outage replies distinguish server errors from denials** (`tcbot/modules/disconnecting.py`, `tcbot/modules/admins.py`): lookup exceptions get retry replies; denial texts fire only on proven verdicts.

- **Secret-scrub hardening on error paths** (`tcbot/utils/error_reporter.py`, `tcbot/__main__.py`): password-only Redis URIs are now covered; console context and Update reprs scrubbed too. Markers stay idempotent.

- **About page no longer double-escapes the community name** (`tcbot/modules/about.py`): the constant is raw with escaping at each use site.

- **Group list truncated to fit Telegram limits** (`tcbot/modules/groups.py`): rendering caps at 3800 chars with an overflow line instead of erroring on large federations.

- **Benign Telegram refusals no longer trip the circuit breaker** (`tcbot/utils/dispatch.py`): `BadRequest` bypasses the failure counter. Seven consecutive benign errors leave the circuit closed; 5 timeouts still trip it.

- **Bounded polling bootstrap retries** (`tcbot/__main__.py`): 5 retries, then the loud crash-and-restart path the watchdog understands. `InvalidToken` still aborts immediately.

- **Ban-ID collision retry for auto-generated IDs** (`tcbot/database/bans_db.py`): one fresh-ID retry on collision; caller-supplied IDs still propagate to protect appeal links.

- **Group record precision fixes** (`tcbot/database/groups_db.py`): re-adds no longer rewrite the first-connect date; no-match deactivates are pure no-ops; pending-only moves no longer mark caches connected.

- **Batch first-name lookups check L1 first** (`tcbot/database/users_cache.py`): cached users serve without I/O; only uncached IDs hit the batch query.

- **Cache writes no longer block requests** (`tcbot/database/cache.py`): Redis writes after a fetch now happen in the background with ordering preserved. Failures still surface in the task log.

- **Stats search falls back to a reply without a result card** (`tcbot/modules/stats.py`): message-less results now send as a reply instead of dropping silently. Paging still works.

- **Connect keeps pending row when registration fails** (`tcbot/modules/helper/workflows/connected_flow.py`): the pending row is removed only after the group record lands, preserving the retry path.

- **Check profile renders Unknown on lookup failure** (`tcbot/modules/helper/workflows/check_flow.py`): failed ban/mute reads render "Unknown (lookup failed)" with a caveat line instead of clean-looking zeros. Success rendering unchanged.

- **Checkme dead detail path removed** (`tcbot/modules/checking.py`): an unreachable second detail block deleted; the banned path now uses the cached admin name instead of a hardcoded literal.

- **Promotion requests deny safely on lookup outage** (`tcbot/modules/admins.py`): failed lookups now get the retry reply instead of proceeding into duplicates.

- **Promotion-approval write ordering** (`tcbot/modules/admins.py`): role grant now precedes resolution, so any failure leaves the request pending and retryable. Error card text unchanged.

- **Transfer surfaces old-owner demote failure** (`tcbot/modules/admins.py`): the reply now warns the operator to grant Admin manually when the old-owner demote fails.

- **Cron endpoint refuses without secret** (`api/cron.py`, `tcbot/__init__.py`, `docs/operations/vercel.md`, `config.env.example`): requests are refused with `503` when no secret is configured. Docs and template state the contract.

- **Ban album double-execution guard** (`tcbot/modules/helper/workflows/ban_flow.py`): proof input is ignored while execution is flagged, with synchronous check-and-set. First submission wins.

- **Join-enforcement role-lookup hardening** (`tcbot/modules/greeting.py`): failed role reads now log loudly and enforce as non-staff, so enforcement never silently skips.

- **Unban cleanup for re-promoted staff** (`tcbot/modules/unbanning.py`, `docs/features/moderation/unbanning.md`): staff targets with a proven active ban are demoted first and the unban proceeds; without one, the refusal stands. Rank safety unchanged.

- **Warn auto-ban aborts safely on DB write failure** (`tcbot/modules/helper/workflows/warning_flow.py`, `docs/features/moderation/warnings.md`): the auto-ban now aborts before touching groups and points at manual `/tcban`. Dead plumbing removed.

- **Auth-guard outage replies** (`tcbot/modules/helper/decorators.py`, `database/users_roles.py`): all four decorators now answer lookup failures with the retry text.

- **Outage-path reply follow-up** (`tcbot/modules/groups.py`): the groups command now answers fetch failures with a server-error message instead of crashing.

- **Stale cache-lock comment** (`tcbot/database/cache.py`): comment corrected.

- **Info-panel crash hardening** (`tcbot/modules/start.py`, `stats.py`, `helper/workflows/stats_flow.py`): the start-menu empty state now edits in place; message-less search renders without card IDs; search input guards instead of asserting.

- **Checkme dead identity branches** (`tcbot/modules/checking.py`): an always-`"self"` classify call and its dead branches removed, saving three DB reads per call. Replies identical.

- **Outage-path replies instead of silent crashes** (`tcbot/modules/disconnecting.py`, `broadcasting.py`, `admins.py`, `helper/workflows/connected_flow.py`): four unguarded DB reads now answer failures with error messages instead of crashing.

- **Approved-join enforcement gaps** (`tcbot/modules/greeting.py`): the ban branch now runs first, and both branches demote best-effort like the member path.

- **Index fail-fast restored** (`tcbot/database/mongos.py`): per-index failures are re-raised after logging, so startup crashes loudly instead of serving without uniqueness indexes.

- **Warn expiry catches up after restarts** (`tcbot/database/scheduler.py`): one catch-up run per missed day instead of silently dropping expiry.

- **Staff ban/kick/mute refusal unblocked** (`tcbot/modules/helper/identity.py`): staff targets now reach auto-demote as documented; rank safety unchanged, Founder refusal stays.

- **Pre-fanout role-lookup hardening** (`tcbot/modules/helper/workflows/ban_flow.py`, `kicking_flow.py`, `muting_flow.py`, `warning_flow.py`): failed re-checks now log loudly and proceed as non-staff, preserving enforcement.

- **Appeal review-card preservation on non-deciding taps** (`tcbot/modules/helper/workflows/appeal_flow.py`): non-deciding taps answer with a popup and leave the card untouched. Only stale cards still edit.

- **Appeal decisions answer retry on role outage** (`tcbot/modules/helper/workflows/appeal_flow.py`): decisions read the role lookup that surfaces failures, and answer retry on outage instead of a false denial.

- **Appeal reviewer lockout with unknown ban owner** (`tcbot/modules/helper/workflows/appeal_flow.py`): falsy owner IDs now disable the lock, matching the documented contract.

- **Appeal submit revalidation and atomic review claim** (`tcbot/modules/helper/workflows/appeal_flow.py`, `tcbot/database/bans_db.py`): submit re-checks pending and cooldown gates, then claims the slot atomically; the race loser is told the appeal is pending.

- **Appeal total-delivery-failure retry in place** (`tcbot/modules/helper/workflows/appeal_flow.py`): the handler stays in the appeal state with state intact instead of ending with no retry path.

- **Appeal approval notification visibility** (`tcbot/modules/helper/workflows/appeal_flow.py`): per-channel failures are now logged instead of swallowed.

- **Staff-guard outage reply honesty** (`tcbot/modules/helper/decorators.py`): the guard reads the cached role like its siblings, so outages get retry text. Outages still refuse safely.

- **Kick/mute/warn replies keep leading ID-like reason tokens** (`tcbot/modules/helper/extraction.py`, `tcbot/modules/kicking.py`, `muting.py`, `warnings.py`, `banning.py`): a shared reply-target helper mirrors resolution priority across all four entries. Non-reply commands unchanged.

- **Mute persists the record before enforcing** (`tcbot/modules/helper/workflows/muting_flow.py`): both writes land first; either failing aborts with no group touched. The origin-chat guard moved above all side effects.

- **Mute keeps unparsable duration tokens in the reason** (`tcbot/modules/muting.py`): tokens are popped only after a successful parse, matching the documented contract.

- **Warn/mute executors answer database outages** (`tcbot/modules/helper/workflows/warning_flow.py`, `muting_flow.py`, `tcbot/database/warns_db.py`): failed reads and writes now answer with retry notices; delete failures raise instead of misreporting empty states.

- **Connect shows progress during the ban/mute replay** (`tcbot/modules/helper/workflows/connected_flow.py`): the prompt edits to a buttonless progress state before the replay, so waits are visible and double-taps impossible. False confirmations stay impossible.

- **Numeric-ID target resolution skips the live lookup on cache hits** (`tcbot/modules/helper/extraction.py`): cached names are authoritative; live calls run only on misses. Usernames stay live-first since they recycle.

- **MongoDB TLS pins the certifi CA bundle** (`tcbot/database/mongos.py`, `pyproject.toml`, `uv.lock`): the client passes `tlsCAFile=certifi.where()`, proven end-to-end against Atlas. Explicit URI values win; verification is never disabled.

- **Duplicate active_mutes index crashed startup** (`tcbot/database/mongos.py`, `docs/architecture/database.md`): the retired plain index is removed and legacy variants are dropped by a pre-step, so all database states start cleanly.

- **Promote/demote answer executor outages** (`tcbot/modules/admins.py`): lookup exceptions get the retry reply; genuinely role-less callers still return silently.

- **Promotion pre-check survives read blips** (`tcbot/modules/helper/workflows/promote_flow.py`): the pre-check falls through to the guarded enqueue, where the pending index still reports lost races.

- **Group-list views never render empty from failed reads** (`tcbot/modules/groups.py`, `tcbot/modules/start.py`, `docs/features/moderation/groups.md`): failed reads edit a retry notice with the keyboard kept for re-taps. Docs updated.

- **Checkme never renders clean verdicts from failed reads** (`tcbot/modules/checking.py`, `docs/features/moderation/check.md`): failed lookups answer retry while preserving the card and its appeal button. Docs updated.

- **Unban/approve fetch groups before deactivating** (`tcbot/modules/helper/workflows/unban_flow.py`, `appeal_flow.py`, `docs/features/moderation/unbanning.md`, `docs/features/appeals.md`): the list loads first and aborts untouched on failure. Docs updated.

- **Warn auto-ban reports reduced scope honestly** (`tcbot/modules/helper/workflows/warning_flow.py`, `docs/features/moderation/warnings.md`): fetch failures are logged and the reply gains a reduced-scope warning pointing at manual `/tcban`. Docs updated.

- **Ban ID reads tolerate sparse records** (`tcbot/modules/helper/workflows/check_flow.py`, `stats_flow.py`): list renderers read via `.get` with fallbacks.

- **Interrupted moderation commands stop cleanly** (`tcbot/modules/banning.py`, `kicking.py`, `muting.py`, `warnings.py`, `unbanning.py`): interruption now stops the handler; only real failures end it mid-way.

- **Ban record lands before the audit log post** (`tcbot/modules/helper/workflows/ban_flow.py`): both helpers write first and post only on success. No phantom ban cards.

- **Unban and appeal-approval load groups before deactivating** (`tcbot/modules/helper/workflows/unban_flow.py`, `appeal_flow.py`, `warning_flow.py`, `docs/features/moderation/unbanning.md`, `docs/features/appeals.md`, `docs/features/moderation/warnings.md`): the list loads first and aborts untouched on failure; the warn auto-ban keeps persist-first order with honest reduced-scope reporting. Docs updated.

- **Outage replies and transient-only failure accounting** (`tcbot/modules/checking.py`, `start.py`, `groups.py`, `admins.py`, `broadcasting.py`, `maintenance.py`, `helper/workflows/promote_flow.py`, `helper/replies.py`): failed card reads answer retry popups; empty renders became retry edits; silent executor paths answer retry; bare role tokens now ask for an explicit target; group-list outage text shares one constant. Broadcast counts only transient failures.

- **Channel senders refused as moderation targets** (`tcbot/modules/helper/extraction.py`, `docs/architecture/helpers.md`): channel-type senders fall through to args and entities instead of creating unenforceable rows. Docs updated.

- **Join path stays silent when enforcement reads fail** (`tcbot/modules/greeting.py`): the welcome is skipped while enforcement is blind. Enforcement itself unchanged.

- **Mute executor and demote observability hardening** (`tcbot/modules/helper/workflows/muting_flow.py`, `demote_flow.py`): missing state aborts with a warning before side effects; missing role rows leave a trace instead of silence.

- **Server-side pagination for ban and user lists** (`tcbot/database/bans_db.py`, `users_cache.py`, `helper/workflows/stats_flow.py`, `check_flow.py`, `docs/features/statistics.md`, `docs/architecture/database.md`, `docs/features/moderation/check.md`): counts, pages, and filters moved onto indexes; only the visible slice travels. Name search uses the anchored cache lookup capped at 30 hits. Docs updated.

- **Single owners for shared tuning, guards, and escaping** (`tcbot/utils/transport.py`, `tcbot/__main__.py`, `tcbot/serverless.py`, `tcbot/modules/connecting.py`, `disconnecting.py`, `tcbot/utils/error_reporter.py`, `tcbot/utils/prefixes.py`, `tcbot/utils/pagination.py`, `tcbot/modules/helper/ban_info.py`, `tcbot/alive.py`, `docs/features/moderation/connecting.md`): HTTP tuning, escaping, regexes, and detail builders each have one owner.

</details>

## [6.5.0] - 2026-09-06

<details>
<summary>6.5.0 changes (click to expand)</summary>

### Changed

- **Todo diligence wording** (`.agents/rules/tooling-validation.md`): the discipline section now requires immediate completion with proof, instant continuation, and explicit cancellation instead of silent drops.

- **Guidance sync for handoff** (`AGENTS.md`, `CONTRIBUTING.md`, `PROMPT.md`, `.agents/skills/`): skill policy mandates loading all matching skills with full reads; stack notes corrected. `CONTRIBUTING.md` is explicitly human-facing; Replit qualifier fixed. Tracked skills refreshed.

- **Docs skill converted to rules** (`.agents/rules/docs-rules.md`): the skill became a canonical rules file; old skill file and manifest entry removed. References updated.

- **Rules reorganization** (`.agents/rules/`): async patterns and role/authorization each gained their own rules file; two redundant skills folded into rules and removed. Six canonical rule files remain. References updated.

- **Dependency refresh** (`uv.lock`): upgrades within pinned bounds (`anyio`, `click`, `idna`, `pymongo`, `ruff`; `typing-extensions` added, `colorama` dropped). Direct dependencies already latest. `apscheduler` stays pinned at `==3.11.3` (pinned; v4 API is incompatible).

- **Todo discipline and slim AGENTS** (`.agents/rules/tooling-validation.md`, `AGENTS.md`, `.agents/rules/security-rules.md`): new Todo and Plan Discipline section; `AGENTS.md` style, architecture, commit, and security sections reduced to pointers; webhook parser boundary added to security rules.

### Added

- **Native Vercel deployment** (`api/webhook.py`, `api/cron.py`, `tcbot/serverless.py`, `vercel.json`, `.python-version`, `docs/operations/vercel.md`): serverless Telegram receiver with secret validation plus a daily warn-expiry cron endpoint. Handler wiring is shared with other transports; `WEBHOOK_SECRET` is mandatory on Vercel. Python pinned to 3.14. Documented limitation: multi-step conversations are best-effort without instance affinity, and one-off timed unbans never fire serverless.

- **Ignore exported GPG keys** (`.gitignore`): exported private key material can never be committed accidentally.

### Fixed

- **Zero-latency identity refresh** (`tcbot/modules/helper/extraction.py`, `check_flow.py`, `stats_flow.py`): detail views render instantly from cache while a background sync refreshes for the next view. Chat detail refreshes titles the same way.

- **Identity sync with age-based revalidation** (`tcbot/modules/helper/extraction.py`, `tcbot/database/groups_db.py`, `stats_flow.py`, `stats.py`): documents fresher than 7 days serve untouched; older ones re-verify live. Group renames persist from the chat detail view.

- **User identity sync protocol** (`tcbot/database/users_cache.py`, `tcbot/modules/helper/extraction.py`, `__main__.py`, `greeting.py`, `connected_flow.py`, `check_flow.py`, `stats_flow.py`, `stats.py`): one shared lookup protocol replaces the private check_flow copy: check the database first, verify live, save on difference. Sparse docs backfill instead of showing `-`.

- **Clickable-name mentions** (`tcbot/utils/formatter.py`): names now render as the clickable `tg://user?id=` link instead of linking the numeric ID in parentheses.

- **ID-only mentions** (`tcbot/utils/formatter.py`): mentions always render the full name as a clickable link built from the numeric ID; username variants removed since usernames change and can be missing. Bare numeric names still render just the link.

- **Error reporting coverage and readability** (`tcbot/utils/error_reporter.py`, ban/mute/unban/appeal flows): fan-outs now log an error-level summary on transient failures so partial failures ship to LOG_ERRORS. Shipping is throttled (20/min with overflow summary). Reports gain an `Action:` hint line.

- **Central clock module** (`tcbot/utils/time_and_date.py`): every clock read goes through one module. Missing helpers added; all call sites migrated. Redis rate limiting intentionally keeps wall-clock scores for cross-process sharing.

- **Primary-group and timeout centralization** (`tcbot/__init__.py`, `tcbot/utils/time_and_date.py`): one `cfg.is_primary_group()` and one `TELEGRAM_LOOKUP_TIMEOUT` replace all inline copies.

- **Promotion queue races** (`tcbot/database/queues_db.py`, `mongos.py`, `helper/workflows/promote_flow.py`, `modules/admins.py`): resolution is now atomic with a pending-only filter; decisions refuse already-resolved requests. One pending request per user via partial unique index. Transfer failures get explicit replies instead of exceptions.

- **Unwarn race ordering** (`tcbot/modules/helper/workflows/warning_flow.py`): removal runs first with an empty-state reply on failure, and the reply re-reads a fresh count. Concurrent unwarns no longer both claim success.

- **Handler robustness pass** (`tcbot/modules/additional.py`, `start.py`, `helper/decorators.py`, `netspeed.py`, `helper/keyboards.py`, `privacy.py`, `help.py`, `utils/logger.py`): asserts became guards, duplicate answers guarded, empty prefixes fixed in the limiter, speedtest bounded at 180 s with non-https fallback to text, plus keyboard, docstring, timestamp, and emit fixes.

- **Scheduled-unban catch-up window** (`tcbot/database/scheduler.py`): one-off unban jobs now allow a 1-hour window instead of silently dropping on restart.

- **Runner crash-loop guard** (`.github/workflows/run-bot.yml`): five deaths within 10 minutes now abort with backoff; cron covers recovery.

- **Appeal decision races and stale submissions** (`tcbot/modules/helper/workflows/appeal_flow.py`): decisions refuse stale or already-decided reviews; reject ordering holds the cooldown even on partial failure. Submit revalidates from the DB and refreshes transient-zero log IDs.

- **Config parsing hardening** (`tcbot/__init__.py`, `config.env.example`): malformed IDs warn and default instead of crashing; empty names restore defaults; topic clamped; `.env` fallback added. Template documents the new rows.

- **CI reliability** (`.github/workflows/`, `.replit`, `docs/operations/ci-cd.md`): dummy secrets for fork safety, serialized auto-fix runs, validated dep PRs, honest concurrency docs, fixed Replit target.

- **Broadcast plain-text fallback** (`tcbot/modules/broadcasting.py`): per-group sends retry as plain text after an HTML rejection, so one typo no longer fails the whole broadcast.

- **Join-path moderation gaps** (`tcbot/modules/greeting.py`): the join notice fires only after a successful ban with ID plus appeal link; mute re-applies demote like bans; approved requests now enforce active bans too.

- **Disconnect ghost and primary pollution** (`tcbot/modules/disconnecting.py`, `connecting.py`, `helper/workflows/connected_flow.py`): deactivation lands before leaving with abort on failure; primary groups refused on connect paths; status edits target the bot's own message; cleanup reports real deactivated counts.

- **Stats detail cursor** (`tcbot/modules/stats.py`, `helper/workflows/stats_flow.py`): detail buttons carry the stable entity ID and reject mismatches; old three-part callbacks keep working.

- **Target and output hardening** (`tcbot/modules/helper/extraction.py`, `tcbot/utils/formatter.py`, `helper/parse_logmsg.py`, `helper/keyboards.py`): UTF-16-safe mention slicing, validated `t.me/` shapes, http(s)-only menu URLs with omission plus warning otherwise.

- **Error reporting hygiene** (`tcbot/utils/error_reporter.py`): shutdown noise removed; token and credential patterns scrubbed before shipping; identity sweep deadline added; send results inspected; groups cache expiry documented.

- **User cache freshness** (`tcbot/database/users_cache.py`, `tcbot/modules/helper/extraction.py`, `helper/workflows/check_flow.py`, `helper/workflows/stats_flow.py`, `modules/stats.py`): triple-shaped cache entries catch last-name-only changes; repeat lookups bounded; one shared identity resolver replaces the private copy; sparse docs resolve instead of showing `-`.

- **New-ban ban_id fork** (`tcbot/modules/helper/workflows/ban_flow.py`): one canonical `ban_id` flows from caller to record, DM, and log patch. Appeal links no longer orphan.

- **Warn-list authorization gap** (`tcbot/modules/warnings.py`): warn history now enforces the same rank check as its siblings; read-only path keeps no identity refusal.

- **Error-report traceback scrub** (`tcbot/utils/error_reporter.py`): the traceback block passes through secret scrubbing before shipping.

- **Cleanup keeps groups on check errors** (`tcbot/modules/maintenance.py`): check exceptions now keep the group with a warning log instead of mass-deactivating healthy groups on a blip.

- **Ban single-proof state wedge** (`tcbot/modules/helper/workflows/ban_flow.py`): the single-media path now clears state in `finally` like the album path, so exceptions still reach the error handler without wedging the next proof.

- **Mute duration overflow** (`tcbot/modules/helper/workflows/muting_flow.py`): values above 100 years fall back to reason text like any other invalid token. Documented examples unaffected.

- **Kick error-reply info leak** (`tcbot/modules/helper/workflows/kicking_flow.py`): the failure reply is now a generic hint; diagnostics stay in logs.

- **Appeal cancel callback ordering** (`tcbot/modules/helper/workflows/appeal_flow.py`): answer first, then edit, mirroring the ban cancel path.

### Removed

- **Dead prefix filter** (`tcbot/utils/prefixes.py`): `ANY_CMD_FILTER` and its custom-prefix support removed. Zero in-tree importers; `ALL_PREFIXES_CMD_FILTER` is the live filter.

- **Dead check_flow re-export** (`tcbot/modules/helper/workflows/check_flow.py`): `build_ban_detail` removed from `__all__`. External consumers import from `ban_info` directly.

- **Dead helpers** (`tcbot/database/warns_db.py`, `groups_db.py`, `modules/helper/keyboards.py`): `user_all_warns()`, `get_group()`, and `back_to_privacy_kb()` removed. Zero callers each; related doc rows updated.

### Documentation

- **Stale version and role references** (`.agents/rules/tooling-validation.md`, `.agents/rules/security-rules.md`, `tcbot/__init__.py`): scheduler version, demote triggers, and timeout docstrings corrected to match the code.

- **Architecture doc sync** (`docs/architecture/database.md`, `utilities.md`, `repository-map.md`): duplicated index row removed; ghost references, counts, and signatures fixed.

- **Doc sync** (`README.md`, `tcbot/__main__.py`, `tcbot/modules/warnings.py`, `docs/features/moderation/warnings.md`, `workflow-overview.md`, `muting.md`): mention format, compose command, scheduler version, warn access, and typos corrected.

- **Doc sync, round 2** (`docs/features/moderation/check.md`, `groups.md`, `kicking.md`, `muting.md`, `docs/features/roles/demote.md`, `docs/architecture/helpers.md`): nonexistent module refs, stale claims, and outdated signatures corrected.

</details>

## [6.4.0] - 2026-09-05

<details>
<summary>6.4.0 changes (click to expand)</summary>

### Changed

- **Error reporter** (`tcbot/utils/error_reporter.py`):
  - Startup now warns on misconfigured report targets instead of failing silently at error time.
  - Owner-DM target refreshes at runtime after ownership transfer instead of staying frozen at startup.
  - Reports carry an explicit type prefix so the same exception can never collide across both paths.
  - One shared wrapper centralizes the logic for both public report functions.
  - Send failures now log through the main logger so they stay visible.
  - Owner-DM failure message renamed so owner-DM failures are unambiguous in logs.
- **Skill manifest** (`skills-lock.json`): manifest now reflects the actual skills directory (stale entries removed, project-local skills added).

- **Docs** (`AGENTS.md`): stale skill references removed; agent meta-tool removal explained.

- **Duplication** (`tcbot/modules/checking.py`): local `_safe_edit` wrapper removed in favor of the shared `safe_edit_cb`. All 10 call sites rewritten with keyword arguments; unused imports dropped.

- **Duplication** (`tcbot/utils/formatter.py`): `mention()` now delegates to `user_ref()` as a backward-compatible alias. Output identical across all input shapes.

- **Type safety** (`tcbot/modules/helper/parse_editmsg.py`): `safe_edit` now takes a minimal edit protocol instead of a concrete `Message`. Both call paths visible from the signature; unused import removed.

- **Style consistency** (`tcbot/utils/prefixes.py`, `tcbot/modules/checking.py`, `tcbot/modules/stats.py`, `tcbot/modules/privacy.py`, `tcbot/modules/netspeed.py`, `tcbot/modules/help.py`, `tcbot/modules/admins.py`): 20 exception clauses split into separate handlers per project convention.

### Added

- **Helper** (`tcbot/modules/helper/parse_editmsg.py`): new `safe_reply` helper wraps reply-plus-log in one call with a human-readable label. Failures log at debug since they are almost always benign. Mass rollout deferred to a follow-up.

### Fixed

- **Conversation state leak on proof executor failure** (`tcbot/modules/helper/workflows/reason_flow.py`): state now clears before re-raise, mirroring the skip path. Stale keys can no longer leak into the next conversation.

- **False-success on unwarn delete failure** (`tcbot/database/warns_db.py`): delete results are now inspected with recount on failure. Failed deletes no longer report success.

- **False-failure counts on ban and warn auto-ban** (`tcbot/modules/helper/workflows/ban_flow.py`, `warning_flow.py`): both executors now count only transient errors like mute and unban already did. Operator totals no longer inflate on benign refusals.

- **Promotion queue sort and user list sort hardening** (`tcbot/database/mongos.py`, `tcbot/database/users_cache.py`): supporting compound index added; sort field validated against known fields with safe fallback.

- **Role lookups deny on errors** (`tcbot/modules/helper/decorators.py`, `tcbot/database/users_roles.py`, `tcbot/modules/admins.py`): lookup failures now reject the action with a retry message.

- **Skipped sends closed cleanly** (`tcbot/utils/dispatch.py`, `tcbot/utils/circuit_breaker.py`): skipped operations are now closed instead of leaking warnings.

- **Single recovery probe on circuit recovery** (`tcbot/utils/circuit_breaker.py`, `tcbot/utils/dispatch.py`): one shared gate permits a single recovery probe; overlapping callers wait.

- **False-success / silent data loss on group connect** (`tcbot/modules/helper/workflows/connected_flow.py`): registration now completes before the prompt edits to "Connected". False confirmations impossible, mirroring the `/tcconnect` path.

- **Duplicate MongoDB index** (`tcbot/database/mongos.py`): redundant `tc_owners` index creation removed. Dead work on every startup gone.

- **Federation infrastructure loss** (`tcbot/modules/disconnecting.py`): both disconnect paths now refuse primary groups, which must stay reachable for fan-out. Shared helper with a clear user-facing message.

- **Database write race** (`tcbot/database/warns_db.py`): conflicting update operators fixed by dropping the redundant field. First warns no longer crash.

- **Stale user data in profile view** (`tcbot/modules/helper/workflows/check_flow.py`): the resolver now walks connected groups after cache and direct lookup fail, and persists what it finds. Common cases resolve; bare-ID fallback retained.

- **Moderation integrity** (`tcbot/modules/greeting.py`): join-auto-ban now demotes best-effort before enforcing, matching the explicit-command pattern. Failures log without blocking enforcement.

- **Stale role after ownership transfer** (`tcbot/modules/admins.py`): transfer now routes cleanup through the role-aware remover, so the new owner holds exactly one role.

- **Executors re-check roles before enforcing** (`tcbot/modules/helper/workflows/ban_flow.py`, `kicking_flow.py`, `muting_flow.py`): executors re-check the role immediately before fan-out and re-demote best-effort, closing the proof-window promotion race.

- **Appeal approval and rejection fixed** (`tcbot/modules/helper/workflows/appeal_flow.py`): approval now aborts on DB-deactivation failure; reject side effects are each inspected and logged; total-delivery failure edits a retry message and keeps state for retry.

- **False-success path** (`tcbot/modules/helper/workflows/unban_flow.py`): the executor now aborts when DB deactivation fails instead of reporting success over records and chats left out of sync.

- **Benign refusals excluded from failure counts** (`tcbot/utils/dispatch.py`, `tcbot/modules/helper/workflows/connected_flow.py`, `muting_flow.py`, `unban_flow.py`): benign Telegram refusals no longer count as failures in moderation fan-outs. One shared classifier owns the distinction.

- **False-success / ghost-group state** (`tcbot/modules/maintenance.py`): leave results are now structured with fully/partially/log-failed states surfaced in the reply. Primary groups guarded at every layer.

- **Moderation integrity** (`tcbot/modules/banning.py`, `kicking.py`, `muting.py`): failed auto-demote now ends the conversation with a manual-demote instruction instead of enforcing under a stale role.

- **Authorization** (`tcbot/modules/unbanning.py`): unban now enforces the executor-vs-target rank check like every other moderation command.

- **Authorization** (`tcbot/modules/admins.py`): transfer now enforces the rank check and clears pre-existing roles, so the new owner holds exactly one role.

- **Authorization** (`tcbot/modules/admins.py`): promotion requests now refuse the anonymous-bot placeholder with a personal-account instruction.

- **False-success path** (`tcbot/modules/helper/workflows/kicking_flow.py`): the kick reply now fires only after unban, DB write, and log post complete, with a warning line when the unban failed.

- **Misleading reply** (`tcbot/modules/checking.py`): `/checkme` now checks for an active ban before role-based early returns, so banned staff reach the appeal path. Founder and Admin exemptions stand.

- **Exception swallowing** (`tcbot/modules/helper/workflows/reason_flow.py`): executor failures now reach the global error handler after state cleanup instead of being swallowed.

- **Documentation drift** (`docs/architecture/database.md`): removed scheduler row and corrected the idempotency note to the real parameter.

- **Documentation drift** (`docs/architecture/helpers.md`): removed dataclass row and corrected the mention description to actual behavior.

- **Documentation drift** (`docs/architecture/utilities.md`): mention descriptions updated to actual output.

### Documentation

- **Docs** (`docs/architecture/repository-map.md`, `database.md`, `helpers.md`, `utilities.md`, `docs/features/appeals.md`, `replit.md`, `README.md`): stale references synchronized across the repository-wide check.

- **Docs** (`docs/architecture/modules.md`, `docs/architecture/repository-map.md`): stale type-alias entries removed to match the actual tree.

- **Docs** (`docs/features/moderation/kicking.md`, `muting.md`, `unbanning.md`, `connecting.md`, `disconnecting.md`, `groups.md`): six missing feature docs added in the standard structure with diagrams and cross-references; docs index updated.

- **Docs** (`README.md`, `docs/getting-started/setup.md`): timeout settings clarified as parsed-but-not-enforced, matching the canonical template wording.

- **Docs** (`config.env.example`): `PREFIXES` default comment corrected to match the loader.

- **Docs** (`docs/features/moderation/banning.md`): ban-flow diagram corrected to the single real state.

- **Docs** (`AGENTS.md`): five missing helper files added to the repository-layout block.

- **Docs** (`docs/architecture/modules.md`): `/tcs` alias documented on the stats row.

- **Docs** (`docs/architecture/helpers.md`): hardcoded module count replaced with an evergreen phrasing.

### Removed

- **Dead code** (`tcbot/modules/types.py`): entire module removed. Zero in-tree consumers; canonical shape documented in the architecture guide.

- **Dead code** (`tcbot/database/users_roles.py`, `tcbot/database/scheduler.py`, `tcbot/modules/helper/extraction.py`, `tcbot/modules/helper/workflows/stats_flow.py`): four zero-caller symbols removed with their orphaned imports.

</details>

## [6.3.0] - 2026-09-02

<details>
<summary>6.3.0 changes (click to expand)</summary>

### Changed

- **Dependency update** (`uv.lock`): `cachetools` patch release, no API changes. No code changes required.

### Added

- **User mentions** (`tcbot/utils/formatter.py`): all user references now include a clickable `tg://user?id=...` link across greetings, logs, profiles, appeals, and summaries.

### Fixed

- **Correctness** (`tcbot/database/users_cache.py`): `None` now means "unknown, preserve existing" for username and last name; clearing requires an explicit empty string. Bans and promotes no longer wipe stored usernames.

- **Correctness** (`tcbot/database/cache.py`): concurrent misses on one key now share a single fetch. Waiters read the same result; different keys stay parallel.

- **Memory** (`tcbot/database/cache.py`): lock entries are dropped after each fetch instead of accumulating forever.

- **Correctness** (`tcbot/modules/helper/workflows/warning_flow.py`): DB-write failure at the warn threshold now appends a `WARNING` line so the admin can repair the record.

- **Correctness** (`tcbot/modules/helper/workflows/warning_flow.py`): failed staff demote at the threshold now reports the failure and asks for a manual retry instead of claiming success.

- **Code quality** (`tcbot/modules/helper/identity.py`, `tcbot/modules/helper/extraction.py`, `tcbot/modules/helper/decorators.py`, `tcbot/modules/disconnecting.py`): well-known Telegram IDs now have one owner in `identity.py`. Duplicate literals gone.

- **Docs** (`README.md`): `FED_WARN_LIMIT` default corrected to `0` (disabled), matching code and canonical references.

- **CI** (`.github/workflows/dependency-update.yml`): contradictory `--frozen` flag removed so weekly runs actually refresh the lockfile.

- **CI** (`Dockerfile`, `.replit`): runtimes updated to Python 3.14 to match the project floor and CI matrix.

- **Correctness** (`tcbot/modules/helper/workflows/ban_flow.py`): numeric proof IDs now flow as a separate parameter instead of parsing the URL string. The crash on every proof-bearing ban is fixed.

- **Correctness** (`tcbot/__init__.py`): tuple-except split into separate clauses per project convention.

- **Security** (`tcbot/modules/warnings.py`): missing guard added on warn-list history. Enumeration now requires the moderator rank.

- **Correctness** (`tcbot/modules/maintenance.py`): leaveall status now reads the correct tuple element. Counts report accurately.

- **Correctness** (`tcbot/modules/start.py`): missing callback answer added on the empty-groups path. The spinner no longer hangs.

- **Security** (`tcbot/modules/groups.py`): no-groups reply now uses the pre-escaped constant like every other surface.

- **Log formatting** (`tcbot/modules/helper/parse_logmsg.py`): numeric ID fields now use code formatting consistently.

- **Code quality** (`tcbot/modules/helper/workflows/stats_flow.py`): missing logger added; silent exceptions now logged at debug.

- **Code quality** (`tcbot/database/warns_db.py`): rollback failures now log with traceback for observability.

- **Code quality** (`tcbot/alive.py`): clock call standardized; unused imports removed.

- **Query optimization** (`tcbot/database/bans_db.py`, `kicks_db.py`, `mutes_db.py`, `warns_db.py`, `users_cache.py`): list queries now request only needed fields and cap at 200 rows.

- **Query optimization** (`tcbot/database/queues_db.py`): the pending-requests list now requests only needed fields with a 200-row cap.

- **Query optimization** (`tcbot/database/warns_db.py`): the most-recent-warn lookup now reads the ID only, served from the index.

- **Code quality** (`tcbot/modules/helper/workflows/ban_flow.py`): datetime import scoped and conditional collapsed per project rules.

- **Query optimization** (`tcbot/database/mongos.py`): new compound index serves active-ban lookups from the index; redundant prefix index removed.

### Documentation

- **Documentation** (`replit.md`): verbatim rules copy replaced with an actual Replit deployment guide.

- **Documentation** (`docs/architecture/database.md`, `docs/operations/backup-and-restore.md`): scheduler references corrected to the installed version and classes.

- **Documentation** (`README.md`): framework stack entry corrected; stale notes removed.

- **Documentation** (`docs/README.md`, `docs/getting-started/setup.md`): `--frozen` flag added to sync commands per project policy.

- **Documentation** (`docs/architecture/database.md`, `docs/features/moderation/banning.md`, `docs/operations/performance.md`): ban index references updated to the current compound set.

</details>

## [6.2.0] - 2026-08-17

<details>
<summary>6.2.0 changes (click to expand)</summary>

### Fixed

- **Security** (`tcbot/alive.py`): webhook route now rejects non-JSON content types at the parser level. Telegram delivery unaffected.

- **Error handler context** (`tcbot/__main__.py`): console error logs now carry the same user/chat/text context as the shipped reports, speeding up debugging.

- **Memory leak** (`tcbot/modules/helper/decorators.py`): rate-limiter buckets now prune entries older than twice the window past 10,000 buckets. No more unbounded growth.

- **Dead code** (`tcbot/modules/groups.py`): redundant always-true guard removed. Never triggered; no safety lost.

- **Type safety** (`tcbot/`): type errors resolved across 14+ modules with guards, safe accessors, and scoped imports; project venv pinned for consistent checks.

- **Security** (CVE-2026-31072, `pyproject.toml`): APScheduler pin retained as an accepted exception. Vulnerable serializers are never instantiated here; monitor PyPI for a patched release.

- **Correctness** (`tcbot/modules/admins.py`): ownership transfer is now atomic-first: owner set before admin grant, so failures can never leave the federation ownerless.

- **Resource bounds** (`tcbot/modules/maintenance.py`): leaveall and cleanup now use the bounded parallel fan-out instead of unlimited parallel sends.

- **Correctness** (`tcbot/database/warns_db.py`): warn-clear replies now report the warns delete count, not the best-effort counter result.

- **Correctness** (`tcbot/database/bans_db.py`): deactivation now uses `modified_count`, so already-inactive bans stop reporting as "deactivated".

- **Robustness** (`tcbot/__init__.py`): malformed env strings fall back to safe defaults with a warning instead of crashing config loading.

- **Correctness** (`tcbot/database/users_roles.py`): role lookups re-raise instead of caching degraded results. Outages can no longer silently bypass authorization.

- **Memory** (`tcbot/utils/error_reporter.py`): error tracker capped at 1000 entries. No more unbounded growth during error storms.

- **Search quality** (`tcbot/database/users_cache.py`): name search is now prefix-anchored, so "dan" matches "daniel" instead of "randy".

- **Correctness** (`tcbot/utils/pagination.py`): non-positive page sizes return an empty chunk instead of crashing on division by zero.

- **Dead code** (`tcbot/database/documents.py`): unused alias removed; used one retained.

- **Validation** (`.github/workflows/*`): all CI workflows now target Python 3.14.

- **Type checking joins the pipeline** (`pyproject.toml`, `pyrightconfig.json`, `.agents/skills/python-code-quality/`): Python target set to 3.14 across config, docs, and CI.

</details>
