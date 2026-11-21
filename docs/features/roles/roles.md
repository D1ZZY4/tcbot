# Roles

This document describes the current role and staff-management behavior implemented by `tcbot/modules/admins.py`, `tcbot/modules/helper/pipelines/promote_flow.py`, `tcbot/modules/helper/pipelines/demote_flow.py`, `tcbot/modules/helper/guards.py` (for `resolve_and_check`), `tcbot/modules/helper/identity.py` (for target identity refusals), `tcbot/database/users_roles.py`, and `tcbot/database/queues_db.py`.

For promote command details, see [`promote.md`](promote.md). For demote command
details, see [`demote.md`](demote.md). For module structure, see
[`../../architecture/modules.md`](../../architecture/modules.md). For shared
helpers, see [`../../architecture/helpers.md`](../../architecture/helpers.md).
For the database layer, see [`../../architecture/database.md`](../../architecture/database.md).

Every staff-management command except `/tcpromoterequests` (`/tcpromote`, `/tcdemote`, `/transferowner`, `/tcunwarn`, `/resetwarns`) classifies the target through `identity.classify(...)` and refuses disallowed identities (self, this bot, Telegram service account, other bots, Owner, and higher-rank staff where applicable) via `identity.refuse_message(action, ident)` before mutating state. `/tcpromoterequests` is the exception: the caller is both executor and target, which would always produce a self-refusal, so it instead checks `get_effective_role` and `queues_db.get_request` directly to reject callers who already have a role or a pending request.

```mermaid
flowchart TD
    Owner[Owner<br/>full power] --> Admin[Admin<br/>broadcast, cleanup, queue]
    Admin --> Developer[Developer<br/>ban, unban]
    Developer --> Moderator[Moderator<br/>kick, mute, warn]
    Moderator --> Member[Regular member]
    Owner -.->|can promote/demote| Admin
    Owner -.->|can promote/demote| Developer
    Owner -.->|can promote/demote| Moderator
    Admin -.->|requests promote| Owner
    Admin -.->|can demote lower| Developer
    Admin -.->|can demote lower| Moderator
```

```mermaid
flowchart TD
    Action{Ban or Kick or Mute action} --> RoleCheck{Target has role?}
    RoleCheck -->|yes| AutoDemote[Auto-demote via Demote class]
    RoleCheck -->|no| Continue[Continue action]
    AutoDemote --> Continue
    Continue --> Apply[Apply ban/kick/mute]
```

## Purpose

The role system controls who can perform moderation and administrative actions. It combines one Owner, Admin records, and custom Developer/Moderator roles into a single effective hierarchy used across bans, kicks, warnings, unbans, promotion flows, and role protection.

## Effective role hierarchy

Effective roles are resolved by `users_roles.get_effective_role(user_id)`:

1. Read the active `role_assignments` row of the user.
2. Validate its `role_key` against the shared rank table.
3. Cache the result in `effective_role_cache`.

Only `developer` and `moderator` are accepted as custom roles: `set_role` refuses anything else on write, and resolution ignores an unknown stored value (logged as an error, treated as no role) so a legacy or hand-edited row can never grant privilege.

The rank table is:

| Effective role | Rank | Catalog role key |
|---|---:|---|
| `owner` | 4 | `owner` |
| `admin` | 3 | `admin` |
| `developer` | 2 | `developer` |
| `moderator` | 1 | `moderator` |
| `None` | 0 | No role |

`ROLE_LABEL` maps these internal names to display labels: Owner, Admin, Developer, Moderator.

Application and database use the same four names, so no translation table exists between them.

## Permission model

The helper `role_rank(role)` converts an effective role into its numeric rank. Executor-versus-target checks go through `guards.resolve_and_check()`, which allows the action only when the executor rank is strictly greater than the target rank. If either role lookup fails, the check fails closed with a retry reply rather than treating the failed lookup as a user with no role; cancellation always propagates.

The rule is applied at two moments. The entry command compares the roles when the moderator starts the flow, and `guards.enforcement_refusal()` compares them again when the action is enforced, because the reason and proof steps stay open for a minute. A target promoted in that window would otherwise be actioned by a moderator who no longer outranks them, so the ban, kick, mute, and warn executors re-read both roles fresh and refuse the action. The enforcement verdict also carries the tier the action needs, so a moderator demoted below that tier during the same window is refused there. The refusal happens before anything is recorded, so it leaves no audit row, no ban record, no warning counter, and no orphan proof behind. A role lookup that fails refuses the action as well.

Common moderation thresholds:

| Action | Minimum effective role |
|---|---|
| `/tcban` | Developer |
| `/tcunban` | Developer/Admin/Owner via `mod_only` |
| `/tckick` | Moderator |
| `/tcwarn` | Moderator |
| `/tcunwarn` | Moderator/Admin/Owner via `basic_mod_only` |
| `/resetwarns` | Moderator/Admin/Owner via `basic_mod_only` |
| Appeal decision buttons | Owner or Admin via `users_roles.get_effective_role` (fresh read) |
| `/tcpromote` | Owner or Admin |
| `/tcdemote` | Owner or Admin |
| `/transferowner` | Owner only |
| `/tcpromotelist` | Owner or Admin via `staff_only` |
| Promotion approve/reject buttons | Owner only |

### The permission catalog

The schema carries a permission catalog next to the role assignments:
`permission_definitions` names the capabilities, `role_permissions` says
which role holds which one, and `role_definitions` gives every role its
priority. The catalog is the reference the tier model is checked against.

`users_roles.has_permission(user_id, permission_key)` is the single
authorization primitive of the schema. It calls the database function
`actor_has_permission`, which reads the active assignment and walks down
to the permission list. It returns `False` for a user without an
assignment, an expired assignment, or an unknown permission, so a failure
never grants privilege.

The handlers gate a command on a tier rather than on a permission key, so
the two have to agree. `tests/test_rbac_catalog.py` pins that: for every
gated command it names the capability and the tier the handler enforces,
and the test fails when the seeded grants no longer match the tier model.
A change to either side has to be a change to both.

| Capability | Tiers that hold it |
|---|---|
| `moderation.ban`, `moderation.unban` | Owner, Admin, Developer |
| `moderation.kick`, `moderation.mute`, `moderation.unmute`, `moderation.warn`, `moderation.unwarn`, `moderation.reset_warnings` | every tier |
| `moderation.review_appeals`, `roles.promote`, `roles.demote` | Owner, Admin |
| `roles.transfer_ownership`, `roles.review_promotion_requests`, `community.leave_all`, `community.speedtest` | Owner only |
| `community.broadcast`, `community.cleanup`, `groups.remove` | Owner, Admin |

## Persistent tables

| Collection | Purpose | Key fields |
|---|---|---|
| `role_definitions` | The role catalog: the display name and the priority of every role. | `role_key`, `display_name`, `priority` |
| `permission_definitions` | The permission catalog: the capability keys and their resource. | `permission_key`, `resource` |
| `role_permissions` | Which role holds which permission. | `role_key`, `permission_key` |
| `role_assignments` | The staff assignments, with their status and their expiry. | `user_id`, `role_key`, `status`, `assigned_by_user_id`, `assigned_at`, `expires_at`, `revoked_at` |
| `promotion_requests` | Stores pending/resolved staff promotion requests. | `request_id`, `target_user_id`, `username`, `first_name`, `requested_role_key`, `requested_by_user_id`, `status`, `requested_at`, `resolved_at`, `resolved_by_user_id`, `decision_note` |

A demotion revokes the assignment row, it never deletes it, so the history of who held which role stays readable. Indexes are ensured for one active assignment per user, at most one active owner, and the role and status filters. `promotion_requests` carries a unique `request_id`, a status index and a target index that serve the pending-list filters, and a partial unique index on `target_user_id` restricted to `status = 'pending'` so each user has at most one open request (the dedup guard both `cmd_promote_request` and the Admin request path rely on).

Role and owner/admin writes invalidate relevant cache entries so permission checks see updated state. Effective-role and owner reads are cached: the per-user effective role serves from an L1 cache with a 60 s TTL and the owner ID from one with a 300 s TTL, so repeated authorization checks (auth decorators, `is_staff`, rate-limit tiering, promotion-request guards) cost zero database round trips on a hit. `set_owner` and `transfer_ownership` clear the entire effective-role cache because the previous owner's key may be unknown to the caller.

## `/tcpromote` behavior

`/tcpromote` assigns a role or starts an approval request, depending on executor role and target role.

Aliases:

- `/tcpromote`
- `/tcp`

Accepted role arguments:

| Argument | Normalized role |
|---|---|
| `admin` | `admin` |
| `developer` | `developer` |
| `dev` | `developer` |
| `moderator` | `moderator` |
| `mod` | `moderator` |

Target resolution supports reply, user ID, and resolvable username.

### Promotion permissions

| Executor | Direct role choices |
|---|---|
| Owner | Admin, Developer, Moderator |
| Admin | Developer, Moderator |
| Developer/Moderator/unroled | No promotion access |

If the command omits the role argument, the bot shows an inline role-selection menu using `keyboards.promote_role_kb(...)`.

Role-selection callback data:

| Button | Callback data |
|---|---|
| Role option | `promo_role:<role>:<target_id>:<executor_id>` (legacy without executor still works) |
| Cancel | `promo_role_cancel:<target_id>:<executor_id>` (legacy without executor still works) |

The callback requires the prompt opener and re-checks the executor's current effective role before executing. If a different staffer taps, the bot answers with an alert and leaves the prompt live. If the opener lost permission, the bot answers with an alert and removes the markup when possible.

### Promotion guardrails

The promotion executor rejects these cases:

- The executor is not Owner/Admin.
- The target cannot be resolved.
- The executor tries to promote themselves.
- The target is the bot.
- The target is Owner.
- The target already has the requested role or a higher role.
- The target is already Admin and the requested role is Developer/Moderator; they must be demoted first.

### Direct Owner promotion to Admin

When Owner promotes a target to Admin:

1. `users_roles.add_admin(target_id, owner_id)` grants the `admin` role and revokes the active Developer/Moderator assignment in the same transaction.
2. `users_cache.upsert_user(...)` caches the display name.
3. A `promoted` log (with `role="admin"`) is sent to `cfg.logs`.
4. The target is notified by DM when possible.
5. The command message is updated/replied with a success message.

### Owner/Admin promotion to Developer or Moderator

When Owner or Admin assigns Developer/Moderator:

1. `users_roles.set_role(target_id, role, assigned_by)` grants the role in one transaction that revokes the assignment it replaces, so the user never holds two active roles.
2. `users_cache.upsert_user(...)` caches the display name.
3. A `promoted` log (with the assigned role) is sent to `cfg.logs`.
4. The target is notified by DM when possible.

### Admin request to promote someone to Admin

Admins cannot directly assign Admin. When an Admin tries to promote a target to Admin:

1. The bot checks for an existing pending request for that target.
2. A new request is inserted into `promotion_requests` with status `pending`.
3. The Owner is fetched from the active owner assignment.
4. The Owner is notified by DM with Approve/Reject buttons if possible.
5. If the Owner DM fails or no owner ID exists, the request is posted to the logs channel as a fallback.
6. The command replies that the request was submitted.

The pending-request guard is target-based: only one pending Admin promotion request is allowed for the same target.

## `/tcpromoterequests` behavior

Aliases:

- `/tcpromoterequests`
- `/tcreqs`

This command lets a user submit a request for themselves to become Admin.

Flow:

1. Anonymous-admin senders (GroupAnonymousBot) are rejected before any lookup.
2. The caller's effective role and any open pending request are fetched in parallel.
3. A caller who already holds a federation role (Owner, Admin, Developer, or Moderator) is told no request is needed.
4. A caller who already has a pending request is told the request is pending.
5. Otherwise, the bot enqueues a new `promotion_requests` document with `target_id` equal to the user's ID and `Promote.request_admin` notifies the Owner.
6. The Owner is notified by DM with approve/reject buttons when possible.
7. The logs channel is used as a fallback notification destination.
8. The user receives a confirmation that the request was submitted.

## Promotion request callbacks

Approve/reject buttons are generated by `keyboards.promo_decision_kb(request_id)`.

| Button | Callback data |
|---|---|
| `Approve` | `promo_approve:<request_id>` |
| `Reject` | `promo_reject:<request_id>` |

Only the Owner can use these callbacks. The handler checks `users_roles.is_owner(admin.id, fresh=True)` before reading the request, so a transfer in another process takes effect immediately instead of lingering for the cache TTL.

### Approval

Approval does the following:

1. Adds the target to `role_assignments` with `users_roles.add_admin(...)`.
2. Marks the request `approved` with `queues_db.resolve(...)`.
3. Best-effort cleanup mirrors the direct Owner path: clears any stale Developer/Moderator row and refreshes the member cache (otherwise the stale row resurrects on the next demote).
4. Sends a `promote_approved_log` to `cfg.logs`.
5. Notifies the target by DM when possible.
6. Edits the review message to append who approved it and removes the keyboard.

### Rejection

Rejection does the following:

1. Marks the request `rejected` with `queues_db.resolve(...)`.
2. Sends a `promote_rejected_log` to `cfg.logs`.
3. Notifies the target by DM when possible.
4. Edits the review message to append who rejected it and removes the keyboard.

## `/tcpromotelist` behavior

Aliases:

- `/tcpromotelist`
- `/tcplist`

This command is staff-only and lists all pending promotion requests. The output includes:

- Target mention.
- Target ID.
- Username when known.
- Request ID.

If no pending requests exist, the bot replies `No pending promotion requests.`

## `/tcdemote` behavior

Aliases:

- `/tcdemote`
- `/tcd`

Demotion removes an Admin, Developer, or Moderator role after a confirmation step.

Flow:

1. Owner/Admin runs `/tcdemote <target>` or replies with `/tcdemote`.
2. The bot resolves executor role and target in parallel.
3. The executor must currently be Owner or Admin.
4. The target must hold a removable role.
5. Owner cannot be demoted through this command.
6. Admin targets can only be demoted by Owner.
7. The bot sends a confirmation keyboard.

Confirmation callback data:

| Button | Callback data |
|---|---|
| `Confirm` | `demote_confirm:<target_id>:<executor_id>` (legacy without executor still works) |
| `Cancel` | `demote_cancel:<target_id>:<executor_id>` (legacy without executor still works) |

The confirmation callback requires the prompt opener and re-checks executor permission and target role before writing. A different staffer tapping gets an alert and the prompt stays live. It revokes the active assignment of the target, whatever role it holds, so no stale row can resurrect the privilege on the next demote.

On success:

- A `demoted` log is sent to `cfg.logs`.
- The target is notified by DM when possible.
- The confirmation message is edited with a success message and keyboard removed.

Cancel answers the callback and edits the message to say no changes were made. New prompts carry the opener, so only that staffer can cancel; legacy callbacks keep working.

## `/transferowner` behavior

Aliases:

- `/transferowner`
- `/tfowner`

Only the current Owner can transfer ownership.

Flow:

1. The target is resolved by reply, user ID, or username.
2. Identity refusal rejects self-transfer, the bot, Telegram, other bots, anonymous-admin, and Owner targets.
3. The current owner is re-read fresh before the mutation. A concurrent transfer or a demotion that happened while the target was classified refuses the command, so an in-flight transfer cannot overwrite a newer owner.
4. `users_roles.transfer_ownership(current_owner.id, target_id)` swaps the owner, revokes the target's previous active role, and grants the previous Owner the Admin role in one transaction under an advisory lock. The transaction re-reads the current owner, so a stale prompt cannot replace a newer owner. A failure leaves both roles untouched instead of committing the swap without the Admin grant.
5. The in-process error-reporter owner is refreshed to the new owner.
6. The owner cache is updated and the effective-role cache is cleared entirely.
7. An `ownership_transferred` log is sent to `cfg.logs` in parallel with the reply.
8. The command replies with the new owner mention.

After transfer, the previous Owner becomes Admin and the new target becomes Owner.

## Auto-demotion on moderation actions

`Demote.execute(..., trigger="ban"|"kick"|"mute"|"warn")` from `pipelines/demote_flow.py` is used before ban/kick/mute when the target has a lower staff role than the executor, and for the warn-threshold staff exemption.

Behavior:

- The target's active role assignment is revoked, so no stale assignment survives in the other collection.
- Send the same `demoted` log to `cfg.logs` as manual demotion (the log never notes the trigger).
- DM the target that their role was removed because they were banned, kicked, or muted.

Ban, kick, and mute command modules block equal/higher-ranked targets before calling auto-demotion, so auto-demotion only applies to lower-ranked staff targets.

A single warning below the warn limit does not auto-demote. However, when the warn limit is reached, `warn_flow` calls `Demote.execute(trigger="warn")` and then exempts the staff target from the auto-ban (staff are never auto-banned via warnings); the threshold warn itself is still recorded. Individual warnings below the threshold leave the role intact.

## Logs

Role and promotion logs are built in `messages/` (`audit_logs.py`):

| Template | Trigger |
|---|---|
| `promoted(target_id, target_fname, role, by_id, by_fname)` | Owner/Admin promotes a user to the named role (Admin, Developer, or Moderator). |
| `demoted(target_id, target_fname, role, by_id, by_fname)` | Role removed. Identical for manual demotion and auto-demote during a ban, kick, or mute (the log template has no trigger parameter). |
| `ownership_transferred` | Owner transfers ownership. |
| `promote_request_log` | Admin promotion request created. |
| `promote_approved_log` | Owner approves a promotion request. |
| `promote_rejected_log` | Owner rejects a promotion request. |

## Edge cases

- Effective role cache can make reads fast, but writes invalidate affected users or clear the cache when ownership changes.
- A user holds at most one live role: both the direct Owner path and the approval path clear any Developer/Moderator row when granting Admin.
- Direct Owner promotion to Admin removes existing Developer/Moderator custom role, and promotion-request approval now does the same.
- Promotion and demotion callbacks re-check current permissions at click time; losing permission after the menu was created blocks the callback.
- Owner cannot be assigned over or demoted through the normal role commands.
- Admin cannot demote Admin; Owner is required.
- Admin cannot directly promote a target to Admin; a request is created instead.
- Pending promotion requests are not deleted after approval/rejection; they are marked with `status`, `resolved_at`, and `resolved_by_user_id`.
- DM notification failures are tolerated in most role flows through `asyncio.gather(..., return_exceptions=True)` or explicit fallback logging.

## Behavior reference

Key role-system behaviors to keep in mind:

1. `get_effective_role` returns the role of the active assignment, mapped to the application vocabulary.
2. `role_rank(None)` returns `0`.
3. `resolve_and_check` allows the action only when executor rank is strictly higher than target rank.
4. Owner can directly promote Admin/Developer/Moderator.
5. Admin can directly promote Developer/Moderator.
6. Admin attempting to promote Admin creates a pending request.
7. Duplicate pending promotion requests for the same target are rejected.
8. Non-Owner cannot approve/reject promotion request callbacks.
9. Owner approval grants the admin role and resolves the request.
10. Owner rejection resolves the request without granting Admin.
11. `/tcdemote` blocks self-demotion and Owner demotion.
12. Admin cannot demote Admin.
13. Confirm demotion revokes the active role assignment of the target.
14. Transfer ownership makes the old Owner an Admin and replaces the owner assignment.
15. Ban/kick/mute auto-demotes lower-ranked staff targets and logs the role removal.
16. Equal-rank and higher-rank targets are protected from ban/kick/mute/warn actions.
