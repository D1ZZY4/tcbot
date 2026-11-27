# Security and authorization

This page defines who may act, on whom, and in which chat. Every ambiguous case
is resolved against denying the action. The guards themselves are part of the
[system spine](../flows/system.md).

## Tier hierarchy

The federation tiers are `owner`, `admin`, `developer`, and `moderator`. Ranks
are compared numerically; a higher rank wins, and equal rank never grants
permission over a peer. The single source of truth is
`tcbot/database/users_roles.py`.

| Tier | Rank | Label | Assignable | Set membership |
|---|---|---|---|---|
| `owner` | 4 | Owner | No, set only by transfer or seed | `OWNER_ADMIN_ROLES` |
| `admin` | 3 | Admin | Yes, by Owner only | `STAFF_ROLES`, `OWNER_ADMIN_ROLES` |
| `developer` | 2 | Developer | Yes | `STAFF_ROLES`, `VALID_ROLES` |
| `moderator` | 1 | Moderator | Yes | `STAFF_ROLES`, `VALID_ROLES` |

`VALID_ROLES = ("developer", "moderator")`; `STAFF_ROLES` is admin, developer,
and moderator; `OWNER_ADMIN_ROLES` is owner and admin. `role_rank()` maps an
unknown or missing role to `0`, and `get_effective_role()` ignores stored values
outside the vocabulary. `guards.required_rank()` maps an unknown tier name to a
value no real role reaches, so a typo can only refuse an action.

## Decorator gates

Handlers apply decorators in a fixed order: `ratelimiter()` outermost, the
required authorization guard second, and `log_execution` innermost.

| Gate | Minimum |
|---|---|
| `owner_only` | Owner. |
| `staff_only` | Admin. |
| `mod_only` | Developer. |
| `basic_mod_only` | Moderator. |

All gates refuse the anonymous-admin placeholder, fail closed on a lookup
error, and re-raise `asyncio.CancelledError`. The `owner_only` gate refreshes the
cached owner role before the rank check later in the same request.

## Permission catalog

Capability checks call `users_roles.has_permission(uid, key)` directly, which
runs the SQL function `actor_has_permission(user_id, permission_key)`. That
function resolves the active assignment, walks its role permissions, and
returns false for a missing, expired, or unknown permission. Key format is
`^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$`.

The seed catalog defines keys across the `audit`, `automation`, `community`,
`groups`, `members`, `moderation`, `roles`, and `rules` resources. Representative
grants:

| Permission | admin | developer | moderator | owner |
|---|---|---|---|---|
| `roles.promote` | yes | no | no | yes |
| `roles.demote` | yes | no | no | yes |
| `roles.review_promotion_requests` | no | no | no | yes |
| `roles.transfer_ownership` | no | no | no | yes |
| `rules.manage` | yes | no | no | yes |
| `rules.view` | yes | yes | yes | yes |

`rules.manage` and `rules.view` are enforced by direct
`users_roles.has_permission()` calls in `rules_editor_steps.py`, `mod_action_steps.py`, and
`ban_rules_step.py`. Capability checks are explicit at the call site; there is
no separate decorator gate.

## Executor and target checks

The decorator answers "may this user run this command at all". The guards in
`modules/helper/guards.py` answer "may this executor act on this specific
target". Both are required; neither substitutes for the other.

| Function | Purpose |
|---|---|
| `resolve_and_check` | Read both roles fresh, check tier and outrank, reply on refusal. |
| `classify_and_check` | Run `identity.classify` and `resolve_and_check` in parallel. |
| `enforcement_verdict`, `enforcement_refusal` | Re-check tier and outrank at enforcement time, after the proof window. |
| `recheck_executor_rank` | Verify a tapper still holds rank on a late conversation tap. |
| `check_callback_staff`, `check_callback_executor` | Answer the callback spinner and re-check rank. |
| `outranks` | Single owner of the rank comparison; equal rank refuses; a role-less target passes. |
| `can_demote_admin` | Demoting an Admin requires the Owner; the Owner is never demotable. |
| `banned_target_refusal` | A banned target must not gain rank. |

Fail-closed rules that apply everywhere: both roles are read with `fresh=True`;
a role-lookup failure refuses; `identity.classify()` raises rather than
degrading a target to `"user"`; cancellation propagates; every tier gate and
capability check rejects on lookup failure.

## Protected targets

`identity.classify()` produces an `Identity` with a `kind` from `IdentityKind`.
`identity.refuse_message()` and `identity.refuse_role()` consult `_REFUSE_KEYS`,
the single table of refused `(action, kind)` pairs.

| Action | Refused identity kinds |
|---|---|
| `ban`, `kick`, `mute` | `self`, `this_bot`, `telegram`, `anon_admin`, `owner` |
| `warn` | `self`, `this_bot`, `telegram`, `other_bot`, `anon_admin`, `owner` |
| `unban` | `self`, `this_bot`, `telegram`, `anon_admin`, `owner`, `admin`, `developer`, `moderator` |
| `unmute` | `self`, `this_bot`, `telegram`, `other_bot`, `anon_admin`, `owner` |
| `promote` | `self`, `this_bot`, `telegram`, `other_bot`, `anon_admin`, `owner`, `admin` |
| `demote`, `transfer`, `unwarn`, `resetwarns` | `self`, `this_bot`, `telegram`, `other_bot`, `anon_admin`, `owner` |

Special IDs are `TELEGRAM_USER_ID = 777000` and `ANONYMOUS_BOT_ID = 1087968824`.
Lower staff roles are deliberately absent from the ban, kick, and mute rows
because those paths demote the target first; refusing there would make the
documented demote unreachable.

## Demote gates

| Gate | Policy | Used by |
|---|---|---|
| `demote_before_enforcement` | Best effort. A lookup or demote failure is logged and enforcement still runs. | Ban, kick, mute, join enforcement. |
| `demote_before_unban` | Fail closed. A failed or no-op demote while the role still resolves blocks the action. | `/tcunban`, appeal approval. |

The best-effort rule exists because the moderation record already exists when
the demote runs, so a transient database failure must not block enforcement.
Unban and appeal approval fail closed because a staff holder must never keep
rank after a ban lifts. See [Roles](../flows/roles.md) and [Connection](../flows/connection.md).

## Role cache freshness

| Cache | L1 TTL | Redis TTL | Prefix |
|---|---|---|---|
| `effective_role_cache` | 60 s | 90 s | `role` |
| `owner_id_cache` | 300 s | 360 s | `owner` |

Display reads use the cached path; enforcement reads pass `fresh=True`, which
routes through `TwoLevelCache.refresh()`. A generation guard discards a fresh
result that overlapped a revocation. Role writes invalidate the effective-role
cache. Ownership transfer uses a generation-guarded owner refresh, verifies
exactly one owner row, then clears all role cache keys.

## Cross-group isolation

Conversations are registered `per_chat=True, per_user=True`. `modules/helper/scope.py`
returns the per-chat, per-user `ctx.user_data` payload directly, so two actions
of one moderator in different groups cannot overwrite each other.
`callback_is_current()` rejects buttons from an older prompt or a callback
with no recorded prompt identity.

`guards.require_federation_origin()` allows private chats only when
`allow_private` is set, short-circuits on `cfg.is_primary_group(chat_id)` or
  `cfg.is_infrastructure_chat(chat_id)`, and
otherwise requires `groups_db.is_connected(chat_id, fresh=True)`. A disconnected
group or a lookup outage blocks the action, which prevents a non-federation chat
from aggregating into a federation-wide threshold ban. Callback prompts may
carry the opener as a trailing `:{executor}` segment so a different tapper gets
an alert while the prompt stays live.
