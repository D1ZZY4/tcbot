# Disconnecting

This page describes group removal implemented by `tcbot/modules/disconnecting.py`.
The decision path is drawn in [the connection diagram](../../pipelines/connection.md).

Related pages: [connecting](connecting.md), [groups](groups.md), and
[banning](banning.md).

## Purpose and ownership

Disconnecting deactivates a group's federation row and makes the bot leave the
chat. The database row is deactivated first; only then does the bot leave, so a
failed deactivation never leaves a live group that the bot has already left.
Primary groups are infrastructure and can never be disconnected.

Ownership: `disconnecting.py` owns both commands and the leave sequence;
`groups_db.py` owns deactivation; `messages/audit_logs.py` builds the log.

## Commands and access

| Command | Alias | Access | Scope |
|---|---|---|---|
| `/tcdisconnect` | none | Federation staff or the group creator | Current group only. |
| `/rmtc <chat_id>` | none | Federation staff | Numeric chat id. |

Both use `ratelimiter(THROTTLE_FEDERATION)` and `log_execution`. `/tcdisconnect`
refuses private chats. `/rmtc` is staff-only and takes an explicit numeric id.

## Guards and sequence

1. Refuse a private chat for `/tcdisconnect`.
2. Refuse a primary group (`cfg.is_primary_group`), which is a required
   enforcement and log destination.
3. Check `groups_db.is_connected(chat.id, fresh=True)`; a failure replies with
   a status failure.
4. For `/tcdisconnect`, check `identity.can_manage_group(..., fresh=True)` so
   only federation staff or the group creator may disconnect.
5. Deactivate the group with `groups_db.deactivate_group()`. A failure replies
   and the bot stays in the group.
6. On success, fan out the log post, `leave_chat`, and the confirmation reply
   in parallel.

## Database impact

`deactivate_group()` moves the `connected_chats` row out of the active set and
invalidates the connection and active-groups caches. Pending rows are removed
as needed. The group list and locale caches are shared, so a later `/tcgroups`
call reads the refreshed state.

## Logging

`messages.group_disconnected_log()` and related builders post to `cfg.logs`.
The confirmation reply is localized. A deactivation failure is logged with the
chat id and surfaced to the operator.

## Edge cases

- A primary group is always refused, even by the Owner, because it carries
  enforcement and log delivery.
- An unknown or already disconnected chat gets a "not connected" reply rather
  than an error.
- A failed deactivation keeps the bot in the group, so the federation does not
  lose a group it still believes is active.
- `/rmtc` uses the same deactivation-first rule as the in-group command.

## Validation hints

Relevant tests include the connection and group-management tests under
`tests/`.

```bash
uv run pytest tests/ -q -k connect
```
