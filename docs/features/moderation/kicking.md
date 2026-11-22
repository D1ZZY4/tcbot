# Kicking

This page describes the current-chat kick implemented by `tcbot/modules/kick.py`
and `helper/pipelines/kick_flow.py`. The flow is drawn in
[the kicking diagram](../../pipelines/kicking.md).

Related pages: [banning](banning.md), [muting](muting.md), and
[shared helpers](../../architecture/helpers.md).

## Purpose and ownership

A kick acts only in the current chat. It is implemented as a Telegram ban
immediately followed by an unban with `only_if_banned=True`, which lets the
user rejoin. Because Telegram rejects bans in private chats, the command
refuses private origins. Proof is optional. The flow writes an audit row before
enforcement and uses a durable reconcile run to repair a failed rejoin.

Ownership: `kick.py` validates and starts the conversation; `kick_flow.py`
builds it through `reason_flow.build_modaction_conv()` and owns the executor;
`kicks_db.py` writes audit rows; `enforcement_db.py` and
`enforcement_worker.py` own the reconcile run.

## Commands and access

| Command | Alias | Access | Origin |
|---|---|---|---|
| `/tckick <target> <reason>` | `/tck` | Moderator and above (`basic_mod_only`) | Connected group only. |

The handler uses `ratelimiter(THROTTLE_MODERATION)`, then `basic_mod_only`, then
`log_execution`. Target resolution uses `min_role="moderator"` and
`allow_private=False`. An inline reason skips the reason prompt and goes
straight to proof collection; overlong reasons fail fast.

## Conversation and callbacks

The kick conversation uses the shared states from `reason_flow.py`:

| State | Value | Meaning |
|---|---|---|
| `WAITING_REASON` | 0 | Awaiting the typed reason. |
| `WAITING_PROOF` | 1 | Collecting optional proof. |
| `WAITING_RULES` | 2 | Picking published rules. |
| `WAITING_RULES_NOTE` | 3 | Entering an optional note. |

Callbacks are `kick_cancel`, `kick_done_proof`, `kick_skip_proof`, and the
shared `rules_step:*` set. Done and Skip claim the `kick_executing` flag before
their first await, so a double tap cannot run the executor twice. The tapper's
rank is rechecked with `recheck_executor_rank(min_role="moderator")`.

## Enforcement and delivery

`execute_kick()` runs `enforcement_refusal(min_role="moderator")` twice: once
before proof upload and audit, and again immediately before the audit record.
Proof upload failure is logged and degrades to a kick without evidence. The
audit row is written with status `completed` before enforcement, then moved to
`failed` if the ban or its follow-up unban fails.

`demote_before_enforcement(trigger="kick")` runs best effort after proof. The
current chat is banned and unbanned; the unban and federation log post run in
parallel. The user-facing summary is composed only after the unban result is
known, so the moderator never sees a success while the target is still banned.

## Database impact

The audit row lives in the kick domain helper (`kicks_db.py`) and records the
chat, target, actor, reason, optional proof archive, and status. The reason,
rules, and proof are archived through `moderation_db` on the same transaction
as the audit row. A failed rejoin queues a `reconcile` enforcement run with
idempotency key `moderation:{action_id}:kick-unban:v1` and exactly one target:
the kick's own chat. The worker accepts the run only for a `kick` action in
`completed` or `failed` status and cancels it when an active federation ban
now holds the target. A successful repair moves the row back to `completed`.

## Logging

`messages.kick_log()` builds the federation log posted to `cfg.logs` with a
proof button when evidence landed. Reason and proof prompts use the rich
transport with no parse mode. Module and flow failures log through the module
logger with the target and action identifiers.

## Edge cases

- A failed ban cancels any in-flight proof upload, marks the audit row failed,
  and replies with the kick error.
- A failed unban gets one bounded retry. If it still fails with a benign
  Telegram refusal, the summary carries a warning; otherwise the row is marked
  failed and the reconcile run is queued.
- A kick never creates a federation ban, so the reconcile run is the only
  durable repair for a target left banned.
- Self, bot, Telegram, anonymous-admin, and Owner targets are refused by
  `identity.classify()`, with lower staff roles demoted first.

## Validation hints

Relevant tests include `tests/test_kick_guard.py` and `tests/test_kick_summary.py`.

```bash
uv run pytest tests/ -q -k kick
```
