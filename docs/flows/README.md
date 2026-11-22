# Flows

This section owns every diagram and every end-to-end description of how TCF Bot
behaves. Each page is authoritative for its domain: it covers the entry point,
the state machine, the database writes, the Telegram delivery, the failure and
retry paths, and the exact names a developer needs. Pages point to each other
instead of repeating another domain's detail.

## Core system

| Page | Covers |
|---|---|
| [System spine](system.md) | Startup, update dispatch, authorization chain, persistence and transport boundary. The anchor for every other page. |
| [Permissions](permissions.md) | Tier gates, decorators, permission catalog, executor-versus-target checks, protected targets, demote gates. |
| [Rate limiting](ratelimit.md) | Global and per-handler throttles, Redis sliding window, circuit breakers, flood-wait handling. |
| [Persistence](persistence.md) | Transaction boundary, enforcement ledger, retry lifecycle, notification outbox, scheduler and pg_cron. |
| [Cache](cache.md) | L1/L2 layers, single-flight, generation and epoch guards, tombstones, FIFO mutation queue, Redis outage behavior. |
| [Transport](transport.md) | Rich payload assembly, send and edit helpers, keyboard conversion, callback answers, error reports, deep links. |
| [Extraction and user data](extraction-user-data.md) | Target resolution order, bounded lookups, MTProto fallback, identity classification, mention cache, erasure. |

## Moderation

| Page | Covers |
|---|---|
| [Banning](banning.md) | Federation ban: commands, re-ban confirmation, rules picker, proof, dual rank gate, decision write, delivery, summary, appeal handoff. |
| [Unbanning](unbanning.md) | Fail-closed demote gate, atomic revoke and queue, per-group delivery, appeal slot handling, repair. |
| [Kicking](kicking.md) | Current-chat ban and rejoin, optional proof, audit row, reconcile repair. |
| [Muting](muting.md) | Duration parsing, apply and revoke runs, timed state machine, join and connect replay. |
| [Warning](warning.md) | Per-group and federation thresholds, staff exemption, automatic ban, conservative clearing, expiry. |
| [Proof](proof.md) | Media filter, two collection models, debounce and flush claim, upload chunking, partial galleries, archive. |

## Staff and member flows

| Page | Covers |
|---|---|
| [Appeals](appeals.md) | Deep link and group tag, atomic submit and slot claim, reviewer windows, approve/reject, durable card edits. |
| [Connection](connection.md) | Manual connect, bot-added flow, bounded replay, join enforcement, disconnect, primary group handling. |
| [Roles](roles.md) | Direct promotion, queued Admin request, demotion triggers, atomic ownership transfer, request expiry. |
| [Community rules](rules.md) | Draft editor, publication lease and reconciliation, member acknowledgement, shared moderation picker. |
| [Check and statistics](statistics.md) | `/checkme` and `/check` drill-down trees, `/tcstats` panes, pagination, batched reads, access tiers. |

## Callback and state registry

The exhaustive list of callback payloads and `WAITING_*` states lives in
[reference/callbacks.md](../reference/callbacks.md) and the keyboards that emit
them in [reference/buttons.md](../reference/buttons.md). This section describes
how those callbacks behave inside each flow; the reference pages list their
exact names, owners, and styles.

## Flow coverage matrix

Each row names the authoritative page for one domain. Entry points, states,
callbacks, tables, and workers are summarized here so a reader can find the
right page without opening all eighteen.

| Flow | Entry | States | Main callbacks | Tables | Worker / retry |
|---|---|---|---|---|---|
| [Banning](banning.md) | `/tcban` | `WAITING_UPDATE_CONFIRM`, `WAITING_BAN_RULES`, `WAITING_BAN_RULES_NOTE`, `WAITING_PROOF` | `ban_continue`, `ban_done_proof`, `rules_step:*` | `moderation_actions`, `_cases`, `_evidence_*`, `moderation_enforcement_*` | enforcement worker, 3 attempts |
| [Unbanning](unbanning.md) | `/tcunban`, appeal approve | none | `appeal_approve_*`, `appeal_reject_*` | `moderation_actions`, `moderation_appeals`, enforcement runs | revoke run, 3 attempts |
| [Kicking](kicking.md) | `/tckick` | `WAITING_REASON`, `WAITING_PROOF`, `WAITING_RULES`, `WAITING_RULES_NOTE` | `kick_done_proof`, `kick_skip_proof`, `kick_cancel` | kick audit rows, `reconcile` run | reconcile run |
| [Muting](muting.md) | `/tcmute`, `/tcunmute` | shared reason states | `mute_done_proof`, `mute_skip_proof` | `moderation_actions`, `active_mutes`, enforcement runs | apply/revoke runs |
| [Warning](warning.md) | `/tcwarn`, `/warns` | shared reason states | `warn_done_proof`, `warn_skip_proof` | `moderation_actions`, `warn_counts` | threshold ban apply run |
| [Proof](proof.md) | shared by all four actions | proof sub-states | `<action>_done_proof`, `<action>_skip_proof` | `_evidence_uploads`, `_evidence_items` | session flush + archive |
| [Appeals](appeals.md) | deep link, `#appeal`, review card | `WAITING_APPEAL` | `cancel_appeal`, `appeal_approve_*`, `appeal_reject_*` | `moderation_appeals`, notification outbox | notification worker, 5 attempts |
| [Connection](connection.md) | `/tcconnect`, `MY_CHAT_MEMBER` | none | `tc_join`, `tc_cancel` | `connected_chats`, `join_requests`, replay runs | connect replay queue |
| [Roles](roles.md) | `/tcpromote`, `/tcdemote`, `/transferowner` | none | `promo_role:*`, `demote_confirm:*`, `promo_approve:*` | `role_assignments`, `promotion_requests` | expiry job |
| [Rules](rules.md) | `/tcrules`, `/rules` | `WAITING_EDITOR_MENU`, `WAITING_CONFIRM_DISCARD` | `rules_edit_draft`, `rules_publish`, `rules_ack:*` | `rule_*` tables | publication lease + reconciliation |
| [Check and statistics](statistics.md) | `/checkme`, `/check`, `/tcstats` | none | `check_*`, `stats_*` | read-only across all domains | background identity/title refresh |

Cross-cutting pages cover the rest: [permissions](permissions.md) and
[rate limiting](ratelimit.md) gate every row; [transport](transport.md) renders
every reply; [persistence](persistence.md) owns the ledger and workers;
[cache](cache.md) guards fresh reads; and [extraction and user data](extraction-user-data.md)
resolves the target before any of these flows act on it.

## Reading order

For a first pass: [system spine](system.md), then [permissions](permissions.md),
then [banning](banning.md) as the most complete worked example, then the remaining
moderation pages, then [persistence](persistence.md) for the worker lifecycle.
