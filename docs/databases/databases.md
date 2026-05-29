# Database Layer

The database layer lives in `tcbot/database/` and is the only place that should perform MongoDB reads and writes. Command modules and workflows should call helper functions instead of calling `mongos.col()` directly.

## Connection manager

`mongos.py` owns the Motor client lifecycle.

| Export | Purpose |
|---|---|
| `connect()` | Creates the `AsyncIOMotorClient`, selects `cfg.db_name`, and pings MongoDB. |
| `ensure_indexes()` | Creates all required indexes on startup. Safe to call repeatedly. |
| `db()` | Returns the active database or raises if `connect()` has not run. |
| `col(name)` | Returns a collection from `db()`. Use only inside database helper modules. |
| `make_short_id(length=10)` | Generates lowercase alphanumeric IDs for records such as bans and promotion requests. |

## Collections and helpers

| Helper | Collection(s) | Main responsibilities |
|---|---|---|
| `users_db.py` | `member_cache`, `tc_owners`, `tc_admins`, `tc_roles` | Member profile cache, owner/admin storage, Tester/Developer custom-role assignment, effective-role resolution, rank comparison, role-cache invalidation. Provides optimized `get_user_mention_data()` for fetching only first_name and username fields. |
| `bans_db.py` | `bans` | Active ban lookup, ban creation/update, unban deactivation, appeal/review metadata, active ban lists. |
| `groups_db.py` | `federated_groups`, `pending_joins` | Connected group state, pending connection requests, group cache invalidation. |
| `users_db.py` | `member_cache` | Cached Telegram profile data from group messages and lookup fallbacks. |
| `warns_db.py` | `warns`, `warn_counts` | Warning history, warning counters, backfill/sync, remove latest warning, clear warnings. |
| `kicks_db.py` | `kicks` | Kick audit records. |
| `mutes_db.py` | `mutes` | Mute audit records. |
| `queues_db.py` | `promotion_requests` | Queued Admin promotion requests and resolution status. |
| `cache.py` | in-memory only | TTL caches for owner, roles, connection status, and active groups. |
| `documents.py` | type-only | `TypedDict` document shapes and `Literal` aliases. |
| `types.py` | type-only | `NewType` primitives such as `UserId`, `GroupId`, `ChatId`, and `BanId`. |

## Member cache optimization

The `member_cache` collection stores user profile data. For performance, use the appropriate query function:

| Function | Fields fetched | Use case |
|---|---|---|
| `get_user(user_id)` | All fields | When you need complete user profile |
| `get_first_name(user_id, fallback)` | `first_name` only | When you only need the name |
| `get_user_mention_data(user_id)` | `first_name`, `username` | Optimized for mention formatting (returns tuple) |

**Performance tip:** Always use `get_user_mention_data()` when building mentions to avoid fetching unnecessary fields like `last_name`, `commit_date`, and `last_updated`.

## Startup indexes

`ensure_indexes()` creates:

| Collection | Index |
|---|---|
| `bans` | `(banned_user_id, is_active)` |
| `bans` | unique `(ban_id)` |
| `tc_owners` | unique `(user_id)` |
| `tc_admins` | unique `(user_id)` |
| `tc_roles` | unique `(user_id)` |
| `federated_groups` | `(chat_id, is_active)` |
| `federated_groups` | unique `(chat_id)` |
| `member_cache` | unique `(user_id)` |
| `warns` | `(user_id, chat_id, timestamp desc)` |
| `warn_counts` | unique `(user_id, chat_id)` |
| `promotion_requests` | unique `(request_id)` |
| `promotion_requests` | `(target_id, status)` |

If a new query depends on a new access pattern, add the matching index in `ensure_indexes()` together with the helper change.

## Role model

Effective roles are resolved in `users_db.get_effective_role()`:

1. Founder from `tc_owners` returns `"founder"`.
2. Admin from `tc_admins` returns `"admin"`.
3. Custom role from `tc_roles` returns `"developer"` or `"tester"`.
4. No role returns `None`.

Rank ordering:

```text
founder = 4 > admin = 3 > developer = 2 > tester = 1 > none = 0
```

Use `users_db.role_rank()` and `users_db.can_act_on()` instead of hand-written comparisons.

## Ban document fields

`bans` documents are represented by `BanDoc` and may contain:

| Field | Meaning |
|---|---|
| `ban_id` | Short unique ban identifier. |
| `banned_user_id` | Target Telegram user ID. |
| `reason` | Moderation reason. |
| `admin_user_id` | Admin who created or updated the ban. |
| `proof_message_id` | Uploaded proof message ID in the proof destination. |
| `log_message_id` | Audit log message ID. |
| `previous_proof_message_id` / `previous_log_message_id` | Prior records when an active ban is updated. |
| `timestamp` | Initial creation time. |
| `updated_timestamp` | Last update time when applicable. |
| `is_active` | Whether the federation ban is active. |
| `update_count` | Number of updates to the ban. |
| `review_message_id` / `review_timestamp` | Appeal review card metadata. |
| `appeal_log_msg_id` / `appeal_submitted_at` / `appeal_link` | Submitted appeal metadata. |

## Warning model

Warnings are stored per user and chat:

- `warns` stores each warning event.
- `warn_counts` stores a counter document for fast limit checks.
- `warns_db._sync_warn_count()` backfills counters from warning history when needed.
- `warning_flow.WARN_LIMIT` is currently `3`.

## Group model

`federated_groups` stores active and inactive group records. Disconnecting marks a group inactive instead of deleting it. `pending_joins` stores temporary connection prompts until the owner accepts or cancels.

## Caches

`cache.py` provides `TTLCache` plus public cache instances:

| Cache | Typical key | Used by |
|---|---|---|
| `effective_role_cache` | `user_id` | `users_db.get_effective_role()` |
| `connected_cache` | `chat_id` | `groups_db.is_connected()` |
| `active_groups_cache` | fixed key | `groups_db.active_groups()` |
| `owner_id_cache` | fixed key | `users_db.get_owner_id()` |

Write helpers must invalidate or refresh related cache entries. For example, role writes invalidate the target user's effective role cache, and group writes clear or update group caches.

## Document typing

Use `documents.py` for MongoDB shapes and `types.py` for nominal ID types in new helpers. These are typing aids; stored MongoDB values remain plain strings, integers, booleans, and datetimes.

## Safety rules

- Do not call `col()` from command modules or workflow files.
- Keep new collection helpers in `*_db.py` files.
- Keep stored schema changes backward-compatible unless a migration plan exists.
- Use `utc_now()` from `tcbot.utils.timedate_format` for stored timestamps.
- Never log secrets or connection strings.
