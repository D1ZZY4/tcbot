# Changelog

All notable changes to this project are documented here. For workflow details, see [`docs/operations/ci-cd.md`](docs/operations/ci-cd.md). For project overview, see [`README.md`](README.md). For contributor rules, see [`CONTRIBUTING.md`](CONTRIBUTING.md). For AI Agents see [`AGENTS.md`](AGENTS.md). For AI agent knowledge see [`docs/README.md`](docs/README.md).

## [Unreleased]

### Added

- **Community rules can be edited, published, and acknowledged from the bot** (`tcbot/modules/rules.py`, `tcbot/modules/helper/pipelines/rules_flow.py`, `tcbot/database/rules_db/`, `docs/features/moderation/rules.md`): staff manage one draft through `/tcrules`, publish it to the main channel as one message per category, and members accept the current version with an `I agree` button on the join greeting. `/rules` is a read-only category menu. Channel messages are edited in place and a failed slot is reconciled by the next publish; there is no separate sync command.
- **Rule publications carry a lock and a reconciliation record** (`alembic/versions/0012_rules_publication.py`, `tcbot/database/rules_db/runs.py`, `tcbot/database/rules_db/publications.py`): a short-lived run prevents two simultaneous publishes, and each channel message slot stores its message id and content hash so an unchanged message is edited rather than reposted.
- **Permission checks by capability** (`tcbot/modules/helper/decorators/auth.py`, `tcbot/database/users_roles.py`): a `permission_only` decorator and the existing `has_permission` helper gate the editor on `rules.manage` without relying on role rank.
- **Community menu links derive from chat ids** (`tcbot/utils/community_links.py`): the Additional menu resolves `MAIN_CHANNEL`, `MAIN_GROUP`, `LOGS`, and `APPEALS` through Telegram, preferring a username over an invite link and omitting a chat that has neither.

### Changed

- **Role vocabulary is now owner, admin, developer, and moderator** (`alembic/versions/0013_role_vocabulary.py`, `tcbot/database/users_roles.py`, `i18n/`): stored founder and tester values are normalised to owner and moderator, and the promotion command no longer accepts the old names. Behavior changes: promotion input and stored role keys use the four final names; the migration is one way.
- **`MAIN_CHANNEL` replaces the static community URL variables** (`tcbot/__init__.py`, `config.env.example`, `README.md`, `AGENTS.md`): `COMMUNITY_CHANNEL_URL`, `COMMUNITY_GROUP_URL`, `COMMUNITY_LOGS_URL`, and `COMMUNITY_APPEAL_URL` are no longer read. Behavior changes: a deployment that relied on those variables must remove them and set the chat ids instead.
- **A reason is required for kicks and mutes** (`tcbot/modules/helper/pipelines/kick_flow.py`, `tcbot/modules/helper/pipelines/mute_flow.py`): both flows now follow the ban and warn flows in asking for a reason without offering Skip. Behavior changes: a kick or mute without a reason now waits for one instead of proceeding.
- **The main group hosts moderation without being connected** (`tcbot/__init__.py`, `tcbot/modules/connect.py`, `tcbot/modules/helper/pipelines/connected_flow.py`): the deployment destinations are recognised as infrastructure and refused by the connect paths, while the configured `MAIN_GROUP` stays a valid federation origin. Behavior changes: a deployment that left `MAIN_GROUP` unset now has to set it to its negative chat id for moderation to work in that group.

### Fixed

- **Overlapping mute writes no longer extend an expiry from stale state** (`tcbot/database/mutes_db.py`): the active row is now locked and the clock read inside the write, so two simultaneous mute actions cannot compute the same expiry from an outdated row. Behavior changes: none; a single mute is unchanged.
- **Moderation history no longer skips or repeats rows between pages** (`tcbot/database/bans_db/`, `tcbot/database/kicks_db.py`, `tcbot/database/mutes_db.py`): entries that share a timestamp now sort by record id, giving every page a stable order. Behavior changes: none.
- **The proof collection cap holds for every debounce window** (`tcbot/modules/helper/pipelines/ban_flow.py`, `config.env.example`, `docs/getting-started/setup.md`): a short album debounce no longer bypasses the limit on collected proof items. Behavior changes: none.
- **Rank refusals render as readable text** (`tcbot/modules/helper/pipelines/ban_flow.py`, `tcbot/modules/helper/pipelines/mute_flow.py`): refusals that name a role now use plain text, so the viewer sees words instead of raw MarkdownV2 escapes. Behavior changes: the affected refusals are sent without Markdown parsing.
- **Warn auto-bans keep warnings outside the narrowed ban scope** (`tcbot/modules/helper/pipelines/warn_flow.py`, `tcbot/modules/helper/pipelines/demote_flow.py`): the pending-warning slate is no longer cleared for warnings the reduced ban scope leaves untouched. Behavior changes: none.
- **A locale change reaches every cache layer** (`tcbot/database/cache/twolevel.py`): an invalidation marker is now written alongside the removed value, so a stale locale cannot reappear after a change made in another process. Behavior changes: none.
- **A queued revocation can no longer be undone by a local L2 read** (`tcbot/database/cache/twolevel.py`, `tests/test_cache_invalidation_race.py`): a read starting after an invalidation but before its queued Redis delete landed could republish the revoked value from L2 into memory for a whole TTL. The cache now marks locally invalidated keys and reads the source until the delete lands. Behavior changes: a read racing a queued revocation now costs one source read instead of serving the cached value.
- **A cancelled Redis ping no longer leaks a connection pool** (`tcbot/database/redis_client.py`): the temporary pool is released when the startup connectivity check is cancelled. Behavior changes: none.
- **Concurrent error reports cannot corrupt each other** (`tcbot/error_reporter.py`): the deduplication state is now serialised across threads. Behavior changes: none.
- **Fatal startup output is redacted before it is shipped** (`tcbot/__main__.py`, `tcbot/error_reporter.py`): sensitive values are stripped from boot-time errors sent to the error channel. Behavior changes: none.
- **Shutdown drains in-flight bot work before closing the client** (`tcbot/__main__.py`): outstanding tasks finish before the Telegram client is closed, avoiding task errors during stop. Behavior changes: none.
- **Every database engine normalises the provider URL the same way** (`tcbot/database/connection_options.py`, `tcbot/database/engine.py`, `tcbot/database/scheduler/`): the scheduler no longer builds connection options from a differently shaped URL than the application engines. Behavior changes: none.
- **A delayed notification cannot complete another worker's item** (`tcbot/database/notifications_db.py`, `tcbot/notification_worker.py`): completion is now bound to the worker's claim. Behavior changes: none.
- **A decided appeal no longer reopens the ban review slot** (`tcbot/database/bans_db/_writes.py`): the slot is restored only while the appeal is still pending. Behavior changes: none.
- **Group appeals accept ordinary long words** (`tcbot/modules/helper/pipelines/appeal_submit_flow.py`): a message containing a long word is no longer mistaken for a malformed appeal tag. Behavior changes: none.
- **Mute durations parse correctly when the reply target is restated** (`tcbot/modules/helper/extraction/resolve.py`, `tcbot/modules/mute.py`): a repeated target is stripped from the command text before the duration is read. Behavior changes: none.
- **An invalid webhook secret is rejected at startup** (`tcbot/__init__.py`, `config.env.example`, `README.md`, `docs/getting-started/setup.md`): boot now fails with an actionable message instead of failing later during Telegram webhook registration. Behavior changes: an out-of-range or malformed `WEBHOOK_SECRET` now prevents startup.
- **A failed scheduled job keeps its failure record** (`tcbot/database/scheduler/jobs.py`, `tcbot/database/schema/functions.sql`): the record survives the next run so the failure remains visible for diagnosis. Behavior changes: none.
- **Account erasure protects the owner and closes open decisions** (`tcbot/modules/maintenance.py`, `tcbot/database/scheduler/jobs.py`, `alembic/versions/0011_erasure_cleanup.py`): the federation owner cannot be erased and pending decisions are closed when an erasure runs. Behavior changes: none.
- **A role-less user can no longer pass the basic moderator gate** (`tcbot/modules/helper/decorators/auth.py`, `tests/test_authz.py`): the tier was compared against a role name that no longer exists, so a missing role matched the zero rank and was admitted. Behavior changes: the decorator now refuses role-less callers; downstream moderator checks already refused them, so command outcomes are unchanged.
- **Stale role names no longer distort statistics and profile details** (`tcbot/modules/helper/pipelines/stats_flow.py`, `tcbot/modules/helper/pipelines/check_flow.py`, `tcbot/modules/helper/pipelines/demote_flow.py`, `tests/test_stats_roles.py`): owner and moderator keys left over from the vocabulary rename never matched, so moderator counts read zero, the staff-only panes never appeared, and the protected-owner demote check never fired. Behavior changes: moderator counts and staff panes now appear for the correct roles.
- **An incident report is no longer lost when its rollover summary fails** (`tcbot/error_reporter.py`, `tests/test_error_reporter_throttle.py`): a transient failure sending the suppressed-error summary no longer discards the current report that triggered the rollover.
- **Redis queue bound documentation matches the enforced limit** (`tcbot/database/cache/redis_io.py`): the queue comments now state that a revocation is dropped at the hard ceiling when no droppable operation can be evicted, matching the behavior the tests exercise. Behavior changes: none.
- **Rules editor actions are re-authorized on every tap** (`tcbot/modules/rules.py`, `tcbot/modules/helper/pipelines/rules_flow.py`): category reorder, delete, rename, and draft text edits now re-check the `rules.manage` capability instead of trusting the command that opened the panel. Behavior changes: a user whose capability was revoked can no longer edit rules from an old panel.
- **The rules picker Cancel button works in moderation flows** (`tcbot/modules/helper/pipelines/reason_flow.py`, `tcbot/modules/helper/pipelines/ban_rules_step.py`): the button sent a callback that no handler matched, so tapping it did nothing. Behavior changes: Cancel now aborts the active kick, mute, warn, or ban rules step.
- **A stale button can no longer act on a newer moderation flow** (`tcbot/modules/helper/scope.py`, `tcbot/modules/helper/pipelines/reason_flow.py`, `tcbot/modules/helper/pipelines/ban_confirmation.py`, `tcbot/modules/warns.py`): conversations are keyed per chat and user, so a Cancel, rule picker, or Done button left on an old prompt could cancel, alter, or prematurely execute a newer action by the same moderator. Every moderation callback now records its prompt identity at entry and ignores taps from any other message. Behavior changes: taps on outdated prompts are acknowledged and discarded instead of changing the active action.

### Documentation

- **Current guides use the shipped role vocabulary** (`README.md`, `AGENTS.md`, `replit.md`, `docs/architecture/helpers.md`): Owner and Moderator replace the former Founder and Tester names in live documentation. Historical release notes are unchanged.
- **Architecture guides describe the new callback guard and cache marker** (`docs/architecture/workflows.md`, `docs/architecture/database.md`): the workflow guide explains stale-tap rejection and the ban confirmation module, and the database guide explains the local pending-invalidation marker.

## Releases

### v7.x

- [7.1.0](docs/releases/v7.1.0.md)

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
