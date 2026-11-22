# Banning: the full system spine and the ban pipeline

This document is the anchor reference for TCF Bot. It describes the runtime spine from startup through update dispatch, authorization, persistence, rich transport, and workers, then follows one federation ban from command entry to appeal delivery.

The sibling documents own other domains and link back here for the shared spine: [unbanning.md](unbanning.md), [kicking.md](kicking.md), [muting.md](muting.md), [warning.md](warning.md), and [proof.md](proof.md). Appeal submission and review are detailed in [appeals.md](appeals.md).

## 1. System spine

### 1.1 Topology

`flowchart` is used because the subject is the shape of the system and the direction of data between components.

```mermaid
flowchart TD
    U[Telegram update] --> WEB["alive.py webhook or polling"]
    WEB --> PTB["python-telegram-bot Application"]
    PTB --> PROC["update_processor: per-conversation serialization"]
    PROC --> FILT["prefix and command filters"]
    FILT --> DEC["decorators: ratelimiter, tier guard, log_execution"]
    DEC --> CMD["Command handler in tcbot/modules"]
    CMD --> GATE["auth: guards, identity, extraction, targets"]
    GATE --> FLOW["Flow in helper/pipelines"]
    FLOW --> DB[("PostgreSQL via engine.db_call")]
    FLOW --> CACHE[("Redis L1 memory and optional L2 cache")]
    FLOW --> RICH["rich_edit and rich_text with MarkdownV2 fallback"]
    RICH --> U
    DB --> WK["enforcement_worker, notification_worker, scheduler"]
    WK --> U
```

### 1.2 Startup sequence

`sequenceDiagram` is used because startup is an ordered set of calls between the application, the database, the scheduler, and the Telegram transport.

```mermaid
sequenceDiagram
    participant Main as __main__.py
    participant Config as Configs
    participant DB as PostgreSQL
    participant Sched as APScheduler
    participant PTB as Telegram Application
    Main->>Config: load environment and validate required secrets
    Main->>DB: apply Alembic migrations in a worker thread
    Main->>DB: connect engine and prime caches
    Main->>Sched: register expiry retention and reconciliation jobs
    Main->>PTB: build application and discover modules
    PTB->>PTB: register command callback and message handlers
    Main->>PTB: set webhook or start polling fallback
```

Module discovery and the `MODULES_LOAD` and `MODULES_NO_LOAD` filters are centralized in `tcbot/modules/__init__.py`. The application owns a single PTB lifecycle. Webhook is the production path; local development may fall back to polling.

### 1.3 Update dispatch layers

```mermaid
flowchart TD
    U[Update] --> KIND{Message or CallbackQuery}
    KIND -->|Message| M1[prefix resolution]
    M1 --> M2[command parser]
    M2 --> M3[rate limiter]
    M3 --> M4[tier guard owner staff mod basic mod permission]
    M4 --> M5[execution logging]
    M5 --> H[Handler]
    KIND -->|CallbackQuery| C1[q.answer before visible work]
    C1 --> C2[parse callback data segments]
    C2 --> C3[scope.callback_is_current]
    C3 -->|stale tap| DROP[acknowledge and discard]
    C3 -->|current| C4[re-authorize executor rank]
    C4 --> C5[rich edit of prompt]
    H --> F[Flow state machine]
```

Handler decorator order is fixed: `ratelimiter()` outermost, the required authorization guard second, and `log_execution` innermost. Message-event handlers are exempt from per-handler rate limits. Callback queries always call `q.answer()` first.

### 1.4 Authorization and target resolution

Every moderation entry passes through the same chain. `guards.resolve_and_check()` reads both roles fresh, refuses an executor below `min_role`, refuses an equal or higher ranked target through `outranks()`, and fails closed on a lookup error. `guards.classify_and_check()` runs `identity.classify()` alongside that rank check.

```mermaid
flowchart TD
    ENTRY[Command with optional target] --> ORIGIN{require_federation_origin}
    ORIGIN -->|denied| STOP[Reply and stop]
    ORIGIN -->|allowed| EX[extract_mod_target]
    EX --> VERIFY[verified ID or username or reply target]
    VERIFY --> CC[classify_and_check: identity plus fresh rank]
    CC --> VERDICT{Allowed}
    VERDICT -->|no| REFUSE[Refusal or retry notice]
    VERDICT -->|yes| PROTECTED{refuse_message hit}
    PROTECTED -->|yes| BLOCK[Block protected identity]
    PROTECTED -->|no| ACTION[Continue to flow]
```

There are two rank gates on a ban. The entry gate is `resolve_and_check()` with `min_role="developer"` plus the `mod_only` decorator. The enforcement gate is `guards.enforcement_refusal()` with the same tier, re-read fresh after the proof window. This dual gate prevents a target promoted mid-window from being actioned by a moderator who no longer outranks them.

### 1.5 Persistence and transport boundary

All database work goes through `engine.db_call()` or `engine.run_transaction()`, which apply the circuit breaker and the call timeout. Decisions, cases, proof, messages, and appeals live in the community moderation tables. Durable per-group work lives in `moderation_enforcement_runs`, `moderation_enforcement_targets`, and `moderation_enforcement_attempts`. Cached reads use the two-level cache with a Redis L2 boundary and in-memory L1 fallback.

User-facing messages render through `rich_edit.py` and `rich_text.py`. Keyboards are rich buttons with the inline keyboard kept as the MarkdownV2 fallback. Plain notices and callback alerts stay unparsed. No HTML parse mode is used anywhere.

## 2. Ban flow, end to end

### 2.1 Conversation states

```mermaid
stateDiagram-v2
    [*] --> WAITING_UPDATE_CONFIRM: active ban found and re-ban offered
    [*] --> WAITING_BAN_RULES: reason inline and rules picker available
    [*] --> WAITING_PROOF: reason inline and no picker
    WAITING_UPDATE_CONFIRM --> WAITING_BAN_RULES: ban_continue from live prompt
    WAITING_UPDATE_CONFIRM --> [*]: ban_cancel
    WAITING_BAN_RULES --> WAITING_BAN_RULES_NOTE: rules_step:other
    WAITING_BAN_RULES_NOTE --> WAITING_PROOF: note accepted
    WAITING_BAN_RULES --> WAITING_PROOF: rules_step:done
    WAITING_BAN_RULES --> [*]: rules_step:cancel
    WAITING_PROOF --> COLLECT: media arrives
    COLLECT --> WAITING_PROOF: more media
    WAITING_PROOF --> EXECUTE: Done tap silence window or 60s cap
    WAITING_PROOF --> [*]: cancel or fallback timeout
    EXECUTE --> [*]: record deliver audit summary and DM
```

### 2.2 Entry to proof collection

`flowchart` is used because this part of the flow is a decision tree with several early exits.

```mermaid
flowchart TD
    CMD[/tcban target reason/] --> G{rate tier origin guards}
    G -->|denied| REFUSE[Refusal reply]
    G -->|ok| RESOLVE[resolve_mod_target min_role developer allow_private true]
    RESOLVE --> REASON[parse_inline_reason and reason length cap]
    REASON --> SAVE[write BAN_USER_DATA_KEYS to flow scope]
    SAVE --> OLD{get_active_ban}
    OLD -->|found| CONF[WAITING_UPDATE_CONFIRM with ban_continue and ban_cancel]
    CONF -->|ban_continue| RULES{show_ban_rules}
    OLD -->|none| RULES
    RULES -->|picker available| PICK[WAITING_BAN_RULES]
    RULES -->|no permission or no rules| PROOF[WAITING_PROOF]
    PICK -->|rules_step:done| PROOF
    PICK -->|rules_step:other| NOTE[WAITING_BAN_RULES_NOTE]
    NOTE --> PROOF
```

The active-ban lookup fails closed: an outage replies with the database retry notice and clears the scope instead of degrading into a fresh ban that wastes a proof round.

### 2.3 Re-ban confirmation and rules picker

`ban_confirmation.py` owns `stale_ban_callback()`, which uses `callback_is_current()` with `ban_prompt_chat_id` and `ban_prompt_msg_id`. A tap from an older prompt is answered and discarded. `on_ban_update_continue()` calls `q.answer()`, re-checks the tapper with `recheck_executor_rank(min_role="developer")`, then delegates to `show_ban_rules()`.

The picker in `ban_rules_step.py` stores selections in `ban_rules` and the optional note in `ban_rules_note`. It asks `users_roles.has_permission(uid, "rules.view")` and reads `rules_db.published_rules()`. With no published rules or no permission it goes straight to the proof prompt.

### 2.4 Proof flush

```mermaid
sequenceDiagram
    participant Mod as Moderator
    participant Flow as ban_flow
    participant Reg as proof_session registry
    participant Bot as Telegram
    Mod->>Flow: photo video animation or document
    Flow->>Reg: append message to (chat_id, user_id) session
    Reg->>Flow: deadline is first arrival plus 60 seconds
    Mod->>Flow: ban_done_proof tap
    Flow->>Reg: set flushing flag synchronously
    Flow->>Reg: cancel the debounce timer task
    Reg-->>Flow: one claim wins over the timer
    Flow->>Bot: upload media group to PROOFS
    Bot-->>Flow: landed items and first message id
```

The proof session is keyed by `(chat_id, user_id)` and carries a snapshot of the flow scope. `_flush_session()` owns the session from its first await. It sleeps in slices bounded by `cfg.album_debounce` and the hard 60 second deadline, then flips `flushing` as a synchronous claim so `Done` and the timer cannot both execute. Its `finally` block removes the registry entry and clears that conversation's ban keys. At shutdown `drain_proof_sessions()` waits for running flushes up to 30 seconds, then cancels those still in their silence window.

### 2.5 Enforcement gate and decision write

The enforcement path re-checks the executor twice: once before any proof upload or record write, and again immediately before the decision is written. A refusal edits the prompt and leaves no record, no proof, and no fan-out behind.

```mermaid
flowchart TD
    EX[_execute_ban] --> G1[enforcement_refusal min_role developer]
    G1 -->|refused| EDIT1[edit prompt with refusal]
    G1 -->|allowed| PRE[prefetch active_groups and gather target locale plus active ban]
    PRE --> UP[upload_proof_media to PROOFS]
    UP --> COMPLETE{proof complete for new ban}
    COMPLETE -->|no| FAIL[edit prompt with proof failure]
    COMPLETE -->|yes| SCOPE[_enforcement_scope with primary and origin groups]
    SCOPE --> G2[enforcement_refusal again after proof]
    G2 -->|refused| EDIT2[edit prompt with refusal]
    G2 -->|allowed| WRITE[_execute_ban_record]
```

`_enforcement_scope()` merges the connected groups, the configured primary group, and the originating group. A ban issued from the bot PM has no group origin, so the scope is the primary group alone. A failed connected-group fetch still leaves the origin group enforced, and the summary carries a scope warning.

### 2.6 Decision, delivery, audit, and summary

```mermaid
sequenceDiagram
    participant Flow as _execute_ban
    participant DB as bans_db and enforcement_db
    participant Work as enforcement_worker
    participant Bot as Telegram
    participant Mod as Moderator
    participant Target as Banned user
    Flow->>DB: create_ban or update_ban with proof and apply run in one transaction
    DB-->>Flow: canonical ban_id and enforcement_run_id
    Flow->>Bot: post federation log with proof and appeal buttons
    Flow->>DB: set_log_message_id
    Flow->>Bot: demote_before_enforcement trigger ban best effort
    Flow->>Work: deliver_queued_run for the apply run
    Work->>Bot: ban_chat_member in each target group
    Work-->>Flow: run report and delivery outcome
    Flow->>Mod: edit prompt with applied summary
    Flow->>Target: DM appeal deep link
```

`create_ban()` and `update_ban()` write the decision, open and close its case, archive proof, link selected rules, and queue the apply run with idempotency key `moderation:{action_id}:apply:v1` in one transaction. A unique partial index permits one active ban per user; the loser of an insert race reuses or supersedes the canonical record, so the log, appeal link, and target button all name the surviving record.

The proof is mandatory for a new ban. A partial gallery, measured by `expected_item_count` against landed items, aborts the ban. A re-ban may carry the previous proof batch forward. See [proof.md](proof.md) for the upload details.

### 2.7 Enforcement worker retry lifecycle

`stateDiagram-v2` is used because this is the lifecycle of one durable delivery target.

```mermaid
stateDiagram-v2
    [*] --> Queued: decision commits with a run
    Queued --> Running: claim_run or claim_runs
    Running --> Succeeded: Telegram accepted
    Running --> Skipped: benign Telegram refusal
    Running --> Failed: transient failure with attempts remaining
    Running --> Terminal: permanent failure or attempts exhausted
    Failed --> Queued: after five minute retry deadline or stale requeue
    Succeeded --> [*]
    Skipped --> [*]
    Terminal --> [*]
```

`run_once()` first calls `requeue_stale_runs()`. An OPEN Telegram circuit pauses the worker entirely so no attempt is burned without a delivery; a HALF_OPEN circuit claims a single probe only. One tick claims at most 10 runs and one run delivers at most 100 targets per pass. Each target has three attempts. `_record_target()` appends an attempt row and moves the target to `succeeded`, `skipped`, or `failed` with a five minute retry deadline. `redrive_run()` lets an operator bring failed targets forward without creating a new decision.

### 2.8 Audit, summary, and appeal handoff

The federation log is posted to `cfg.logs` through `messages.ban_log()` or `messages.ban_update_log()`. The log keyboard carries the proof link and an appeal deep link built by `appeal_deep_link(bot_username, ban_id)`. The moderator prompt is edited in place with `banning.summary.body`, including the applied, failed, and pending counts from `delivery_outcome()`. The target receives a DM with the same deep link and `appeal_button_btn()`. A `telegram.error.Forbidden` on that DM is treated as expected. See [appeals.md](appeals.md) for the submit and review sequence.

## 3. Exact names for this flow

### 3.1 States

| Owner | State | Value |
|---|---|---|
| `reason_flow.py` | `WAITING_REASON` | 0 |
| `reason_flow.py` | `WAITING_PROOF` | 1 |
| `reason_flow.py` | `WAITING_RULES` | 2 |
| `reason_flow.py` | `WAITING_RULES_NOTE` | 3 |
| `ban_flow.py` | `WAITING_PROOF` | 0 |
| `ban_flow.py` | `WAITING_UPDATE_CONFIRM` | 1 |
| `ban_rules_step.py` | `WAITING_BAN_RULES` | 2 |
| `ban_rules_step.py` | `WAITING_BAN_RULES_NOTE` | 3 |

### 3.2 Callback data

| Callback data | Owner | Meaning |
|---|---|---|
| `ban_cancel` | `ban_flow.py` and `ban_rules_step.py` | Cancel the live ban prompt |
| `ban_continue` | `ban_confirmation.py` | Continue a re-ban from a live prompt |
| `ban_done_proof` | `ban_flow.py` | Flush collected proof now |
| `rules_step:pick:<id>` | `ban_rules_step.py` | Toggle one rules item |
| `rules_step:done` | `ban_rules_step.py` | Confirm the rules selection |
| `rules_step:other` | `ban_rules_step.py` | Enter an optional custom note |
| `rules_step:clear` | `ban_rules_step.py` | Clear the selection |

### 3.3 Functions

| Function | Owner | Role |
|---|---|---|
| `cmd_ban_start` | `bans.py` | Validated entry point |
| `_ask_update_confirm` | `bans.py` | Re-ban prompt and prompt identity |
| `ban_conversation` | `ban_flow.py` | ConversationHandler factory |
| `on_proof_received` | `ban_flow.py` | Buffer proof into a session |
| `on_done_proof` | `ban_flow.py` | Claim and run the flush from Done |
| `_flush_session` | `ban_flow.py` | Debounce timer flush owner |
| `_execute_ban` | `ban_flow.py` | Full enforcement orchestration |
| `_execute_ban_record` | `ban_flow.py` | Decision write and federation log |
| `on_ban_update_continue` | `ban_confirmation.py` | Re-ban confirmation handler |
| `stale_ban_callback` | `ban_confirmation.py` | Prompt freshness guard |
| `show_ban_rules` | `ban_rules_step.py` | Rules picker entry |
| `demote_before_enforcement` | `demote_flow.py` | Best-effort pre-fanout demote |
| `run_once` and `deliver_queued_run` | `enforcement_worker.py` | Durable delivery |

### 3.4 Persistence touchpoints

| Table or helper | Writer | Purpose |
|---|---|---|
| `moderation_actions` | `bans_db._writes` | Ban decision and lifecycle |
| `moderation_cases` | `moderation_db` | One investigation per incident |
| `moderation_evidence_uploads` | `moderation_db` | Landed proof batch |
| `moderation_messages` | `bans_db._writes` | Federation log references |
| `moderation_enforcement_runs` | `enforcement_db` | Durable apply and revoke queue |
| `moderation_appeals` | `bans_db._writes` | Appeal record and review slot |
| `notifications_outbox` | `notifications_db` | Durable review-card edits |

## 4. Continue reading

- [unbanning.md](unbanning.md): fail-closed demote gate, atomic revoke and queue, per-group delivery.
- [kicking.md](kicking.md): ban-then-unban and reconcile repair.
- [muting.md](muting.md): timed state machine, replay, and unmute.
- [warning.md](warning.md): thresholds, exemption, and clear rules.
- [proof.md](proof.md): media filter, debounce, upload, and archive.
- [appeals.md](appeals.md): appeal submission and staff decisions.
