# Roles

This page describes the federation role hierarchy and the safety rules around
it. Grant and revoke flows are drawn in [the roles diagram](../../pipelines/roles.md),
and the gates are detailed in [permissions](../../pipelines/permissions.md).

Related pages: [promote](promote.md), [demote](demote.md), and
[banning](../moderation/banning.md).

## Role vocabulary

The vocabulary is owned by `tcbot/database/users_roles.py` and seeded in
`database/schema/seed.sql`.

| Role | Rank | Label | Assignable |
|---|---:|---|---|
| Owner | 4 | Owner | No, set only by seed or transfer. |
| Admin | 3 | Admin | Yes, by the Owner only. |
| Developer | 2 | Developer | Yes. |
| Moderator | 1 | Moderator | Yes. |

`RoleName` is `Literal["owner", "admin", "developer", "moderator"]`.
`VALID_ROLES` is `("developer", "moderator")`, the only directly assignable
custom roles. `ROLE_ALIASES` accepts `admin`, `developer`, `dev`, `moderator`,
and `mod` at command entry. `STAFF_ROLES` is admin, developer, and moderator;
`OWNER_ADMIN_ROLES` is owner and admin. `role_rank()` maps an unknown value to
0, so an unknown role never grants privilege.

## Source of truth and freshness

Role assignments live in `role_assignments`, with definitions and permissions
in `role_definitions`, `permission_definitions`, and `role_permissions`.
`get_effective_role(user_id, fresh=True)` bypasses the cache for enforcement
and authorization decisions. Display reads may use the cache. Role and owner
caches have L1 TTLs of 60 and 300 seconds with Redis TTLs of 90 and 360
seconds; a generation guard discards a read that overlapped a revocation.

Every role write invalidates the effective-role cache. An ownership transfer
uses a generation-guarded owner refresh, verifies exactly one active owner,
then clears all role cache keys.

## Tier gates and permissions

`tcbot/modules/helper/decorators/auth.py` exposes the tiers:

| Gate | Minimum |
|---|---|
| `owner_only` | Owner. |
| `staff_only` | Admin. |
| `mod_only` | Developer. |
| `basic_mod_only` | Moderator. |
| `permission_only(key)` | The named permission through `has_permission()`. |

All gates reject anonymous admins and fail closed on a lookup error. The
permission catalog uses keys such as `roles.promote`, `roles.demote`,
`rules.manage`, and `rules.view`. `rules.manage` is the direct user of
`permission_only` on the rules editors; the flows also check `rules.view`.

## Executor and target checks

Decorators answer whether a user may run a command; guards answer whether they
may act on a specific target. `guards.resolve_and_check()` reads both roles
fresh, checks the minimum tier, checks that the executor outranks the target,
and replies on refusal. `outranks()` refuses equal rank, and a role-less target
passes. `can_demote_admin()` requires the Owner to demote an Admin, and the
Owner is never a demotion target.

Protected identities are defined by `identity.classify()` and the refusal
table in `identity.py`. See [permissions](../../pipelines/permissions.md).

## Demote gates

| Gate | Policy | Used by |
|---|---|---|
| `demote_before_enforcement` | Best effort. A lookup or demote failure is logged and enforcement still runs. | Ban, kick, mute, join enforcement. |
| `demote_before_unban` | Fail closed. A failed or no-op demote while the role still resolves blocks the action. | Manual unban and appeal approval. |

The best-effort rule exists because the moderation record already exists when
the demote runs. Unban and appeal approval fail closed because a staff holder
must never keep rank after a ban lifts.

## Ownership transfer

`users_roles.transfer_ownership()` runs in one transaction under advisory lock
`7_313_919_265_517_001`. It re-reads the current owner under the lock, revokes
the new owner's active assignment, writes the new owner row, and grants the
previous Owner the Admin role in the same transaction. The executor's
ownership is re-read fresh at the mutation point. A failed transfer changes
no role.

## Edge cases

- A stored role outside the vocabulary is ignored by rank checks.
- A role lookup failure never degrades a target to "user".
- A transfer cancels a pending promotion request for the new owner.
- Promotion request expiry is controlled by `PROMOTION_REQUEST_TTL_DAYS`,
  default 7, with 0 disabling expiry.

## Validation hints

Relevant tests include `tests/test_role_*.py`, `tests/test_promotion_*.py`, and
`tests/test_demote_*.py`.

```bash
uv run pytest tests/ -q -k role
```
