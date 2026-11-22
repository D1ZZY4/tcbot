# Demote

This page describes manual and automatic demotion implemented by
`demote_flow.py`, `admins.py`, and the moderation flows. Trigger semantics are
listed in [the roles diagram](../../pipelines/roles.md).

Related pages: [roles](roles.md), [promote](promote.md), and
[banning](../moderation/banning.md).

## Purpose and ownership

Demotion removes a target's active federation role, posts a log, and DMs the
target. It is used manually by staff and automatically before enforcement or
as a threshold exemption. The `trigger` selects the DM wording only; the role
removal is the same operation.

Ownership: `demote_flow.py` owns `Demote.execute()` and both pre-enforcement
gates; `admins.py` owns the manual command and confirmation callbacks;
`users_roles.py` owns the assignment write.

## Commands and callbacks

| Command | Alias | Access |
|---|---|---|
| `/tcdemote <target>` | `/tcd` | Staff (`staff_only`). |

The command uses `ratelimiter(THROTTLE_MODERATION)`, then `staff_only`, then
`log_execution`. It resolves the target, classifies the identity, checks
`guards.can_demote_admin()` so demoting an Admin requires the Owner, and shows
a confirmation card.

| Callback | Effect |
|---|---|
| `demote_confirm:<id>[:<exec>]` | Confirm the demotion after rechecking rank. |
| `demote_cancel:<id>[:<exec>]` | Cancel and leave the role untouched. |

The optional executor segment proves prompt ownership; a different tapper is
alerted and the prompt stays live.

## Triggers

`Demote.execute(bot, target_id, target_fname, target_role, executor_id, executor_fname, trigger=None)`
returns whether a role row was actually removed.

| Trigger | Meaning |
|---|---|
| `None` | Manual `/tcdemote` confirmation. |
| `ban`, `kick`, `mute` | Best-effort demote before enforcement fan-out. |
| `warn` | Warn-threshold exemption: demote instead of ban. |
| `unban` | Fail-closed pre-unban gate. |
| `appeal` | Fail-closed appeal-approval pre-unban gate. |

Join enforcement runs with `executor_id = 0`. The Owner role is never demotable;
a found Owner is returned so the caller can refuse enforcement.

## Best effort versus fail closed

`demote_before_enforcement()` returns the demoted role or `None` and never
raises. It is used by ban, kick, mute, and join enforcement, because the
moderation record already exists when it runs and a transient database failure
must not block enforcement. The target may keep a role until join enforcement
or a manual `/tcdemote` repairs it.

`demote_before_unban()` returns an `UnbanGate` and fails closed:

| Value | Meaning |
|---|---|
| `PROCEED` | The role was removed or was already gone. |
| `DEMOTE_FAILED` | The demote raised. |
| `ROLE_SURVIVED` | No row was cleared but the role still resolves. |

Both `DEMOTE_FAILED` and `ROLE_SURVIVED` block the unban. A no-op demote
re-reads the live role with `fresh=True` to avoid a split-brain between the
identity classification and the rank check.

## Database impact

Demotion revokes the active row in `role_assignments` and invalidates the
effective-role cache for the target. The operation is covered by the same
generation guards as other role writes, so a concurrent grant cannot be
resurrected by an in-flight read.

## Logging

`messages.demoted()` builds the federation log. The DM wording follows the
trigger from the catalog. A best-effort failure is logged loudly with the
target and trigger, while the moderation flow continues.

## Edge cases

- Demoting an Admin requires the Owner.
- The Owner is never a demotion target.
- A stale confirmation from a demoted staff member is rejected by the fresh
  rank check.
- A failed fail-closed gate aborts the unban with a localized notice.

## Validation hints

Relevant tests include `tests/test_demote_*.py` and
`tests/test_role_assignment_rules.py`.

```bash
uv run pytest tests/ -q -k demote
```
