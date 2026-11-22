# Warnings

This page describes the warning system implemented by `tcbot/modules/warns.py`
and `helper/pipelines/warn_flow.py`. Thresholds, exemption, and clearing are
drawn in [the warning diagram](../../pipelines/warning.md).

Related pages: [banning](banning.md), [roles](../roles/roles.md), and
[check](check.md).

## Purpose and ownership

A warning records a per-group incident and can escalate to an automatic
federation ban when a threshold is reached. Warnings are scoped to the origin
group; a federation-wide threshold can also be configured. Clearing moves
rows to `revoked` rather than deleting them, preserving the audit trail.

Ownership: `warns.py` owns command entries; `warn_flow.py` owns filing,
threshold evaluation, and the auto-ban; `warns_db.py` owns locked writes and
the live count views.

## Commands and access

| Command | Alias | Access | Scope |
|---|---|---|---|
| `/tcwarn <target> <reason>` | `/tcw` | Moderator and above (`basic_mod_only`) | Connected group only. |
| `/tcunwarn <target>` | `/tcunw` | Moderator and above | Current group. |
| `/warns <target>` | `/warnlist` | Moderator and above (`THROTTLE_READ`) | Read-only history. |
| `/resetwarns <target>` | `/clearwarns` | Moderator and above | Current group. |

The warn command resolves with `bot_check=True`, because a proven bot cannot
accumulate meaningful warnings. A staff target emits a notice but the warning
still proceeds. Escape filters keep the management commands out of the warn
conversation fallback.

## Conversation and callbacks

The warn conversation uses the shared `reason_flow.py` states
`WAITING_REASON` (0), `WAITING_PROOF` (1), `WAITING_RULES` (2), and
`WAITING_RULES_NOTE` (3). Callbacks are `warn_cancel`, `warn_done_proof`,
`warn_skip_proof`, and the shared `rules_step:*` set. An inline reason skips
to proof collection.

## Filing and thresholds

`execute_warn()` runs the enforcement gate twice at `min_role="moderator"`
and uploads optional proof before filing. `warns_db.add_warn()` takes a
user-wide advisory lock and then a per-chat lock, in that fixed order, so a
filing and a clear cannot deadlock. It opens a case, archives proof, inserts a
completed `warn` decision with an expiry derived from `cfg.warn_expiry_days`,
links rules, closes the case, and reads the count from the `warn_counts` view
in the same transaction.

Threshold evaluation:

- Per group: `count >= cfg.warn_limit` (default 3, minimum 1) triggers an
  automatic federation ban with notice `warnings.autoban.notice_per_group`.
- Federation: when `cfg.fed_warn_limit > 0` (default 0, disabled), a live
  cross-group sum at or above the limit triggers the same ban.
- Otherwise the reply is the plain issued notice.

A failed federation count or role lookup aborts with an honest failure reply.
Staff members are exempt: `Demote.execute(trigger="warn")` removes the role,
then `demote_before_enforcement(trigger="warn")` runs again immediately before
the ban so a promotion between the two cannot survive. An Owner verdict stops
the automatic ban.

## Clearing rules

For a threshold ban, the scope is the connected groups, the primary group, and
the origin group. When no ban is active, `bans_db.create_ban(action_origin="automated", ...)`
files the ban with the warn proof attached but not required. Clearing is
conservative:

- A complete enforcement with all groups landed calls `clear_all_warns()`.
- A partial enforcement calls `clear_warns_for_chats()` only for landed groups;
  failed groups keep their warnings so the threshold can fire again.
- A reduced scope is never complete, even if every known group accepted.

`any_ban_ok` is true when a ban row exists, one group accepted the ban, or a
delivery is still pending. A pending delivery is not a creation failure.

## Database impact

Warnings are `moderation_actions` rows with `action_type = 'warn'` and
`scope_type = 'chat'`. `warns_db` owns `add_warn`, `federation_warn_count`,
`clear_all_warns`, and `clear_warns_for_chats`. The `warn_counts` view,
`get_warns()`, and `remove_last_warn()` exclude expired decisions at query
time. `cfg.warn_expiry_days = 0` disables expiry. Clearing writes `revoked`,
never a delete.

## Logging

`messages.warn_log()`, `messages.unwarn_log()`, and `messages.resetwarns_log()`
build the federation log posts. Threshold notices and issued replies use
catalog keys. Failures log with the target and chat identifiers.

## Edge cases

- A total enforcement failure leaves warnings in place and reports a threshold
  failure notice.
- A ban delivery still pending is reported as pending, not failed.
- Expired warnings remain in history but no longer count toward a threshold.
- The `>=` limit is deliberate: after a total failure the count still equals
  the limit, so the next warning re-fires the auto-ban.

## Validation hints

Relevant tests include `tests/test_warn_*.py`.

```bash
uv run pytest tests/ -q -k warn
```
