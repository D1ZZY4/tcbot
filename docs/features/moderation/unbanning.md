# Unbanning

This page describes manual unban implemented by `tcbot/modules/unban.py` and
`helper/pipelines/unban_flow.py`. The fail-closed gate and durable revoke are
drawn in [the unbanning diagram](../../pipelines/unbanning.md).

Related pages: [banning](banning.md), [appeals](appeals.md), and
[roles](../roles/roles.md).

## Purpose and ownership

An unban lifts an active federation ban, withdraws pending appeals, releases
the review slot, and queues a durable revoke run that lifts the restriction
in every managed group. The operation is idempotent and fails closed on role
and demote failures.

Ownership: `unban.py` validates and resolves; `demote_flow.py` owns the
fail-closed demote gate; `unban_flow.py` owns the executor;
`bans_db._lifecycle` owns the revoke transaction; `enforcement_worker.py`
delivers the revoke.

## Command and access

| Command | Alias | Access | Origin |
|---|---|---|---|
| `/tcunban <target>` | `/tcunb` | Developer and above (`mod_only`) | Bot DM or a connected or primary group. |

The handler uses `ratelimiter(THROTTLE_MODERATION)`, then `mod_only`, then
`log_execution`. It runs three independent reads in parallel with
`asyncio.gather(return_exceptions=True)`: `identity.classify()`, a speculative
`bans_db.get_active_ban()`, and `guards.resolve_and_check(min_role="developer")`.
Cancellation is preserved with `throw_if_cancelled()`.

## Fail-closed demote gate

A staff target is normally not federation-bannable, so "nothing to undo" is the
right reply. The exception is a target re-promoted while banned: the active
ban blocks the join-time demote, so the role would survive the unban.
`_cleanup_role()` reconciles the two fresh reads and either one proving staff
forces the gate to run.

`demote_before_unban()` returns an `UnbanGate`:

| Value | Meaning | Caller behavior |
|---|---|---|
| `PROCEED` | The role was removed or was already gone. | Continue to `execute_unban`. |
| `DEMOTE_FAILED` | `Demote.execute(trigger="unban")` raised. | Reply and stop. |
| `ROLE_SURVIVED` | No row was cleared but the role still resolves. | Reply and stop. |

Unlike the best-effort ban, kick, and mute gate, this one fails closed.

## Revoke transaction and delivery

`execute_unban()` fetches active groups before revoking and re-runs
`guards.enforcement_refusal(min_role="developer")` after the group load.
`bans_db.revoke_ban_and_queue_unban()` performs one transaction:

1. Lock the active ban rows with `FOR UPDATE`.
2. Ensure the acting staff member exists so the run's foreign key cannot fail.
3. Withdraw every pending appeal on those actions.
4. Move the ban to `revoked`, stamp `revoked_at`, and drop review-slot metadata.
5. Queue one `revoke` run per action with idempotency key
   `moderation:{action_id}:revoke:manual:v1` and the full group list.
6. Queue a review-card edit in `notifications_db` when a review chat and
   message were supplied.

The worker delivers the revoke only when the action status is `expired` or
`revoked` and the action type is `ban` or `mute`. A revoke run is cancelled
when `newer_active` is true, because lifting this restriction would undo a
newer ban. `revoked == 0` or a missing run id means another process already
revoked the ban, so the reply is the idempotent "no active ban" notice.

## Database impact

The revoke transaction updates `moderation_actions`, `moderation_appeals`, and
the action metadata together, then inserts enforcement runs and targets. The
notification outbox row closes the review card. `delivery_outcome()` reports
the total, applied, failed, and pending groups; a group that left the
federation is pending rather than silently dropped.

## Logging

`messages.unban_log()` builds the federation log posted to `cfg.logs`. The
command reply reports the per-group outcome and names failed groups. Role and
demote failures are logged loudly because they block the action.

## Edge cases

- A failed category demote aborts the unban instead of silently proceeding.
- A transaction failure replies with the database retry notice and leaves the
  ban intact.
- A disconnected group during the proof window has no target row; when it
  reconnects, `queue_connect_replay()` restores any still-active decision.
- Failed targets are retried while attempts remain. `redrive_run()` lets an
  operator bring failed targets forward without filing a new decision.
- An OPEN Telegram circuit pauses the worker so no attempt is burned without a
  delivery.

## Validation hints

Relevant tests include `tests/test_unban_flow.py`, `tests/test_demote_*.py`,
and `tests/test_enforcement_worker.py`.

```bash
uv run pytest tests/ -q -k unban
```
