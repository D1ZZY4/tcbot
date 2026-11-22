# Statistics

This page describes the federation statistics panel implemented by
`tcbot/modules/stats.py` and `helper/pipelines/stats_flow.py`. The drill-down
structure is listed in [callbacks](../pipelines/callbacks.md).

Related pages: [check](moderation/check.md),
[roles](roles/roles.md), and [performance](../operations/performance.md).

## Purpose and ownership

`/tcstats` presents a federation overview and paged drill-downs for the staff
roster, cached members, connected groups, active bans, and a ban search. The
overview degrades honestly: a failed count is shown as unavailable rather than
as zero.

Ownership: `stats.py` owns the command and callbacks; `stats_flow.py` owns the
view builders (`OverviewViews`, `PeopleViews`, `ChatViews`, `BanViews`,
`SearchViews`); `buttons/stats.py` and `buttons/drills.py` own keyboards.

## Command and access

| Command | Alias | Access |
|---|---|---|
| `/tcstats` | `/tcs` | Anyone (`THROTTLE_READ`). |

The command has no tier guard. The overview button set adapts to the viewer:
drill-down panes that list federation-wide records are shown to staff, and
the callbacks re-check rank freshly. Every callback uses
`ratelimiter(THROTTLE_CALLBACK)` and `log_execution`.

## Overview and roster

The overview gathers the owner id, role counts, active ban count, active group
count, total users, and, for the viewer, owner status and effective role in one
`asyncio.gather(return_exceptions=True)`. A `degraded` notice is added when any
core count failed. The staff roster lists Owner, Admins, Developers, and
Moderators with batched mention data; names that are placeholders are resolved
live with a bounded lookup and a bounded fan-out.

## Drill-downs

| Callback family | View |
|---|---|
| `stats_main` | Overview. |
| `stats_admins` | Staff roster. |
| `stats_users:<page>` | Paged cached-member list. |
| `stats_user_item:<page>:<id>` | One member detail card. |
| `stats_chats:<page>` | Paged connected-group list. |
| `stats_chat_item:<page>:<id>` | One group detail card. |
| `stats_bans:<page>` | Paged active-ban list. |
| `stats_ban_item:<page>:<ref>` | One ban detail card. |
| `stats_bans_search` | Open the search prompt. |
| `stats_search_item:<n>` | One search result. |
| `stats_search_back`, `stats_search_cancel` | Leave search. |

Pages hold six items. Page arithmetic uses `clamp_page()` and `paginate()`.
Detail callbacks carry a stable identifier so a tap from a stale page is
refused. Group detail fires a background title refresh through the
`group title refresh` task tracker, and member detail fires an identity
refresh through the `identity refresh` tracker so the view stays instant.

## Search

`stats_bans_search` opens a prompt; the next text message is captured as the
query. A numeric query loads the active ban directly; a name query uses
`users_cache.search_by_name()` with a limit of 30 and then filters active bans
for those ids. Results render as a numbered list; an empty result state is
explicit. Search context is stored in `ctx.user_data` and cleared on exit.

## Database impact

Views read `users_roles`, `bans_db`, `groups_db`, and `users_cache`. Reads use
`db_call` and batched helpers such as `get_mention_data_batch()` and
`get_first_names_batch()` to avoid per-row queries. List reads are cached
through `active_groups()` where applicable.

## Logging and rendering

Cards use the shared `ban_info` detail builder and the rich transport. A failed
read logs at warning level with the view name and shows a localized error with
a back keyboard, never an empty list that would claim zero records. Empty
states are explicit and localized.

## Edge cases

- A degraded overview shows the unavailable fields rather than zeros.
- A stale page or search result is refused and shows an unavailable notice.
- A failed background refresh leaves the cached value visible; it does not
  block the view.
- Search is read-only and never exposes proof media directly, only a link.

## Validation hints

Relevant tests include `tests/test_stats_roles.py`, `tests/test_check_pagination.py`,
and `tests/test_pagination.py`.

```bash
uv run pytest tests/ -q -k stats
```
