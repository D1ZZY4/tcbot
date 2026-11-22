# Promote

This page describes direct promotion and the queued Admin request implemented
by `tcbot/modules/admins.py`, `promote_flow.py`, and `promo_decision_flow.py`.
The grant table and approval card are drawn in
[the roles diagram](../../pipelines/roles.md).

Related pages: [roles](roles.md), [demote](demote.md), and
[permissions](../../pipelines/permissions.md).

## Purpose and ownership

Promotion grants a federation role. Only the Owner grants Admin outright; an
Admin who requests Admin for someone else creates a request that the Owner
decides. Developer and Moderator can be granted directly by staff according
to the grant table.

Ownership: `admins.py` owns command and callback entries; `promote_flow.py`
owns `Promote` and `request_admin()`; `promo_decision_flow.py` owns the Owner's
decision; `users_roles.py` owns assignment writes; `queues_db.py` owns requests.

## Commands and access

| Command | Alias | Access |
|---|---|---|
| `/tcpromote <target> [role]` | `/tcp` | Staff (`staff_only`). |
| `/tcpromoterequests <target>` | `/tcreqs` | Staff. |
| `/tcpromotelist` | `/tcplist` | Staff (`THROTTLE_MODERATION`). |
| `/promo_approve:<id>` callback | none | Owner. |
| `/promo_reject:<id>` callback | none | Owner. |

The promote command uses `ratelimiter(THROTTLE_MODERATION)`, then `staff_only`,
then `log_execution`. A bare role token with no explicit target or reply is
refused, because name search could promote a stranger.

## Grant table

`Promote.available_roles_for(executor_role)` is the single owner:

| Executor | Roles offered or granted |
|---|---|
| Owner | Admin, Developer, Moderator. |
| Admin | Developer, Moderator. |
| Anything else | None. |

`Promote.execute()` re-reads both roles with `fresh=True` at the mutation point,
because classification and the bot probe can take seconds and a demotion in
that window must not still grant rank. A failed lookup refuses the grant. A
banned target is refused.

`assign_admin()` and `assign_subrole()` write the role, perform a best-effort
display-name upsert, then send the audit log and a DM in one bounded gather.
The assignment revokes the previous active role in the same transaction.

## Owner approval card

When an Admin targets Admin, `request_admin()` checks for a banned target and
an existing request, enqueues the request, and looks up the Owner in parallel.
The card goes to the Owner by DM, falling back to the log channel. One open
request per target is enforced by a partial unique index.

`on_promo_decision` delegates to `execute_promo_decision()`:

1. Approve or reject callbacks are `promo_approve:<id>` and `promo_reject:<id>`.
2. Authorization is `is_owner(admin.id, fresh=True)`; a failure alerts and
   leaves the shared card untouched.
3. A request whose status is not `pending` is refused early.
4. Approval refuses an Owner target, because rewriting it as Admin would leave
   the federation ownerless, and applies the ban guard.
5. `queues_db.resolve()` runs before `add_admin()` on approve and before the
   card edit on reject, so the atomic claim decides a concurrent tap race.
6. `answer_ack()` runs after the decision is reached but before the
   notification fan-out.

If `add_admin()` fails after a won claim, the request stays approved and an
operator grants the role manually. That gap is preferred to granting rank
against a losing reject.

## Database impact

Assignments write `role_assignments`. Requests live in `promotion_requests`
with statuses `pending`, `approved`, `rejected`, `cancelled`, and `expired`.
`expire_stale_requests()` marks pending rows past `expires_at` as expired and
stamps `resolved_at`; expiry runs before each enqueue so an abandoned request
frees the one-pending slot. The TTL comes from `PROMOTION_REQUEST_TTL_DAYS`
(default 7, minimum 0, where 0 disables expiry).

## Logging

`messages.promoted`, `promote_request_log`, `promote_approved_log`, and
`promote_rejected_log` build the federation log posts. The target receives a DM
in the resolved locale. Decisions acknowledge the callback exactly once.

## Edge cases

- Self-promotion and promoting above one's own rank are refused.
- A banned target is refused in both direct and queued paths.
- Concurrent submissions resolve through the unique pending index rather than
  duplicating the queue.
- A transfer cancels a pending request for the new owner.

## Validation hints

Relevant tests include `tests/test_promotion_*.py`, `tests/test_queues_enqueue.py`,
and `tests/test_role_assignment_rules.py`.

```bash
uv run pytest tests/ -q -k promote
```
