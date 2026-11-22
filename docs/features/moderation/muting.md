# Muting

This page describes the group mute and unmute implemented by
`tcbot/modules/mute.py` and `helper/pipelines/mute_flow.py`. The state machine
and replay are drawn in [the muting diagram](../../pipelines/muting.md).

Related pages: [banning](banning.md), [kicking](kicking.md), and
[connection](connecting.md).

## Purpose and ownership

A mute restricts a member's ability to send messages in every active connected
group. It may be permanent or timed. A timed mute expires at query time, so no
sweep is needed to produce an honest active view. Join handling and group
connection replay active mutes so the restriction survives re-entry and new
groups.

Ownership: `mute.py` parses duration and starts the conversation;
`mute_flow.py` owns the apply and revoke executors; `mutes_db.py` owns the
decision helpers; `enforcement_worker.py` delivers restrictions.

## Commands and access

| Command | Alias | Access | Origin |
|---|---|---|---|
| `/tcmute <target> [duration] <reason>` | `/tcm` | Moderator and above (`basic_mod_only`) | Connected group only. |
| `/tcunmute <target>` | `/tcunm`, `/tcum` | Moderator and above | Connected group only. |

The command uses `ratelimiter(THROTTLE_MODERATION)`, then `basic_mod_only`, then
`log_execution`. After target resolution it strips a restated reply target,
then tries the first remaining token with `parse_duration()`. A token is
popped only when it parses; an unparsable token stays in the reason text so
nothing is silently dropped. Accepted suffixes are `s`, `m`, `h`, `d`, `w`,
`mo`, and `ye`, with a 100-year cap.

`cmd_unmute` is a single-action command that delegates to
`targets.run_staff_action(action="unmute", ...)`. An escape filter keeps
`/tcunmute` from being swallowed as reason text by the mute conversation.

## Conversation and callbacks

The mute conversation uses the shared `reason_flow.py` states
`WAITING_REASON` (0), `WAITING_PROOF` (1), `WAITING_RULES` (2), and
`WAITING_RULES_NOTE` (3). Callbacks are `mute_cancel`, `mute_done_proof`,
`mute_skip_proof`, and the shared `rules_step:*` set. Done and Skip claim the
execution slot before their first await and recheck the tapper's rank.

## Apply, revoke, and replay

`_execute_mute()` computes `until = utc_now() + duration` for a timed mute or
`None` for a permanent one, builds `ChatPermissions(can_send_messages=False)`,
and runs the enforcement gate twice at `min_role="moderator"`, before and
after proof. `mutes_db.record_mute()` writes the decision, case, optional
proof archive, rule links, and apply run in one transaction with idempotency
key `moderation:{action_id}:apply:v1`. `demote_before_enforcement(trigger="mute")`
runs best effort after the record commits.

A later mute supersedes the prior one: a new permanent mute clears the expiry,
and a new timed mute keeps the later of the new and stored deadlines. The
stored `duration_seconds` is the remaining lifetime while the original request
is kept in metadata.

`execute_unmute()` loads the active mute, fetches groups before revoking, and
calls `mutes_db.revoke_mute_and_queue_unmute()` in one transaction with
idempotency key `moderation:{action_id}:revoke:manual:v1`. The worker restores
full permissions with `ChatPermissions.all_permissions()`. `revoked == 0` is an
idempotent "no active mute" reply.

Join handling replays active mutes through `active_mute_docs()`. When a group
connects, `enforcement_db.queue_connect_replay()` queues one bounded apply run
per active ban or mute for that chat.

## Database impact

A mute is one `moderation_actions` row with `action_type = 'mute'` and a
partial unique index allowing one active mute per target. Fields include
`expires_at`, `duration_seconds`, `case_id`, `evidence_upload_id`, and
`metadata`. The apply and revoke runs are durable work in the enforcement
tables, with per-target statuses and up to three attempts.

## Logging

`messages.mute_log()`, `messages.unmute_log()`, and the proof caption builders
produce federation log posts. The moderator prompt is edited with a delivery
summary. Duration display uses `fmt_duration()` from `time_and_date.py`. All
user-facing text comes from the catalog, and messages are sent through the
rich transport with no parse mode.

## Edge cases

- A mute whose deadline passes while its apply run waits is cancelled rather
  than served late.
- A revoke run with `newer_active` true is cancelled so a replayed restriction
  cannot undo a newer decision.
- An unparsable or out-of-range duration token remains in the reason and the
  mute becomes permanent.
- A timed mute that expires needs no row rewrite; the active views read the
  deadline at query time.
- Self, bot, Telegram, and protected targets are refused; lower staff roles
  are demoted at enforcement time.

## Validation hints

Relevant tests include `tests/test_mute_*.py` and `tests/test_time_and_date.py`.

```bash
uv run pytest tests/ -q -k mute
```
