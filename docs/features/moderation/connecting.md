# Connecting

This page describes group onboarding implemented by `tcbot/modules/connect.py`
and `helper/pipelines/connected_flow.py`. The decision tree, replay, and join
enforcement are drawn in [the connection diagram](../../pipelines/connection.md).

Related pages: [disconnecting](disconnecting.md), [groups](groups.md), and
[banning](banning.md).

## Purpose and ownership

Connecting a group makes it a managed enforcement destination. Telegram
administrator rights in the group are the authorization; there is no separate
federation approval step. On connect, active bans and mutes are replayed into
the new group, and any remainder is queued as durable work.

Ownership: `connect.py` owns the command, the `MY_CHAT_MEMBER` event, and the
join callbacks; `connected_flow.py` owns `complete_join()`; `groups_db.py`
owns connection state; `enforcement_db.py` owns replay runs; `greeting.py`
owns join-time enforcement.

## Commands and events

| Entry | Access | Scope |
|---|---|---|
| `/tcconnect` (alias `/tccon`) | Group administrator | Group only. |
| `MY_CHAT_MEMBER` bot-added update | Event driven | Group or supergroup. |
| `tc_join`, `tc_cancel` callbacks | Owner of the pending prompt | Pending prompt. |

The command uses `ratelimiter(THROTTLE_FEDERATION)` and `log_execution`. It
gathers the sender's membership, `is_connected(fresh=True)`, `get_pending()`,
and the bot's membership in one round trip. Database failures fail closed.

## Guards

| Guard | Outcome on failure |
|---|---|
| Group or supergroup | Refuse with a group-only reply. |
| Infrastructure chat (`cfg.is_infrastructure_chat`) | Refuse; log, proof, appeal, and main destinations are not managed groups. |
| Anonymous admin (`identity.is_anon_admin`) | Refuse; the name cannot be attributed. |
| Sender is administrator or creator | Refuse. |
| Primary group (`cfg.is_primary_group`) | Refuse; it is already an enforcement destination. |
| Connection and pending state | Fail closed on a database error. |
| Bot rights | Refuse and add a pending row for later retry. |

Required bot rights are `can_delete_messages`, `can_restrict_members`, and
`can_invite_users`.

## Bot-added flow

`on_bot_added()` handles added, promoted, demoted, and removed events. A
primary group is re-registered with `ensure_primary_group()`. An infrastructure
chat is ignored. A pending row with an attributable owner and admin rights is
auto-completed; an anonymous add stores owner `0` and leaves the prompt for the
creator's Connect tap. On removal the group is deactivated first and a log is
posted only when it was connected.

## Replay and durability

`complete_join()` adds the group, removes the pending row, harvests admin
identities, then replays active bans and mutes in rounds of eight through
`fan_out()`. The replay is bounded by a 20-second budget and a 500-user cap.
Whatever the budget, cap, or a stopped replay leaves unapplied is still an
active decision: `enforcement_db.queue_connect_replay()` writes one bounded,
idempotent apply run per decision against the one new chat, retried three
times with 0.2-second backoff. A truncated or timed-out replay returns a
"blind" flag and shows a warning instead of a clean success.

## Join-time enforcement

`greeting.py` re-checks active decisions whenever someone joins a connected
group. `on_new_member` enforces in every connected group and greets only in the
primary group. `on_join_request` declines banned users and fails closed on a
ban-read error. `on_join_request_approved` re-applies a ban or mute because
approval produces no new-member service message. A failed enforcement read
suppresses the welcome, and the demote step is best effort except for the
protected Owner, who is never banned or muted on join.

## Database impact

Connection state lives in `connected_chats` and `join_requests` through
`groups_db.py`. Replay writes enforcement runs and targets. `add_group()`
must succeed or the whole connect fails. Connection and group locale reads use
the shared caches, so a toggle does not keep a divergent per-user copy.

## Logging

`messages.group_connected_log()` and `group_connection_rejected_log()` build
the staff-facing posts. The connection reply reports the applied, failed, and
pending replay counts. Failures log with the chat id.

## Edge cases

- A group with missing bot rights gets a pending row so a later rights grant
  can auto-complete it.
- A deactivation failure on disconnect leaves the bot in the group and reports
  the failure rather than leaving a ghost group.
- A replay item that is a benign Telegram no-op is not treated as a failure.
- Primary groups ignore join decisions.

## Validation hints

Relevant tests include `tests/test_connect_*.py`, `tests/test_complete_join.py`,
and `tests/test_greeting_semaphore.py`.

```bash
uv run pytest tests/ -q -k connect
```
