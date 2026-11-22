# Groups

This page describes the connected-groups list implemented in
`tcbot/modules/groups.py` and the shared panels in
`helper/messages/panels.py`.

Related pages: [connecting](connecting.md), [disconnecting](disconnecting.md),
and [statistics](../statistics.md).

## Purpose and ownership

`/tcgroups` lists the federation's active connected groups. A toggle switches
between a condensed view and a detailed view with full chat IDs. The list reads
the shared `active_groups()` cache rather than keeping a per-user copy.

Ownership: `groups.py` owns the command and the two toggle callbacks;
`messages/panels.py` owns `render_groups()`; `buttons/menus.py` owns
`tcgroups_btn()`.

## Command and callbacks

| Command | Alias | Access | Scope |
|---|---|---|---|
| `/tcgroups` | `/tcg` | Anyone | Bot DM or group. |

The handler uses `ratelimiter(THROTTLE_READ)` and `log_execution`. It reads
`groups_db.active_groups()` and replies with the condensed view plus the toggle
keyboard.

| Callback | Effect |
|---|---|
| `groups_details` | Switch to the detailed view with full chat IDs. |
| `groups_simple` | Switch back to the condensed view. |

The toggles answer the callback and read `active_groups()` in parallel with
`asyncio.gather(return_exceptions=True)`. Answering first keeps the client
spinner from hanging.

## Database impact

`active_groups()` is a two-level cache with an L1 TTL of 30 seconds and an
optional Redis L2 of 45 seconds, keyed under `__all__`. A failed read is never
rendered as an empty list, because that would claim zero connected groups
during an outage. The keyboard is kept so a re-tap retries.

## Logging and rendering

The list renders through `render_groups()` with the resolved locale. A failed
read logs at warning level with the exception and shows a localized retry
notice. All button labels come from `button.toml`.

## Edge cases

- An empty but successful read shows the localized "no groups" notice.
- A read failure keeps the keyboard and shows an error instead of claiming the
  federation has no groups.
- The same shared list is used by the start-menu group panes, so the two views
  cannot drift.

## Validation hints

Relevant tests include group-list and panel tests under `tests/`.

```bash
uv run pytest tests/ -q -k groups
```
