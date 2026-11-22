# Check

This page describes `/checkme` and `/check` as implemented in
`tcbot/modules/check.py` with `helper/ban_info.py` and
`helper/pipelines/check_flow.py`. The drill-down structure is listed in
[callbacks](../../pipelines/callbacks.md).

Related pages: [banning](banning.md), [appeals](appeals.md), and
[statistics](../statistics.md).

## Purpose and ownership

`/checkme` shows the caller's own federation status with an appeal link when
banned. `/check` builds a comprehensive profile of any user: identity, role,
active ban, ban history, warnings by group, kicks, mutes, and appeals. Both are
read-only and use fuzzy target matching because they cannot mutate state.

Ownership: `check.py` owns commands and callbacks; `check_flow.py` owns the
view builders and pagination; `ban_info.py` owns the shared ban summary and
detail; `buttons/check.py` owns the keyboards.

## Commands and access

| Command | Alias | Access | Scope |
|---|---|---|---|
| `/checkme` | `/cme` | Anyone | The caller. |
| `/check <target>` | `/c` | Anyone | A resolved user. |

Both use `ratelimiter(THROTTLE_READ)` and `log_execution`. There is no
authorization guard. Bots and the anonymous-admin placeholder are short-circuited
for `/checkme` because they hold no federation records.

## `/checkme`

The handler fetches the caller's role and active ban in parallel. Role-aware
replies cover Owner, Admin, Developer, and Moderator; a regular user with no
ban sees a clean notice. An active ban produces a summary with the user
mention and ID, reason, actor, commit date, and buttons for Details, optional
Proof, and Appeal. The appeal button uses the same deep link as the ban log.

| Callback | Effect |
|---|---|
| `checkme_detail:<ban_id>` | Load the active ban and edit to the full detail view. |
| `checkme_back:<ban_id>` | Edit back to the summary view. |

A failed ban lookup leaves the live card untouched and shows a retry alert. If
the ban is no longer active when Details is tapped, the alert says so.

## `/check`

The target resolves by reply, numeric ID, `@username`, or partial name. A
typed ID or username that verifies as a real user different from the quoted
sender overrides the reply; `/check` additionally prefers any resolving
argument, including a partial-name match, because it is read-only.

The opening profile shows identity, role, and the active-ban summary. Each
section opens a paged drill-down:

| Callback family | Section |
|---|---|
| `check_main:<user>` | Return to the profile. |
| `check_bans:<user>:<page>` | Ban history. |
| `check_ban_item:<user>:<ref>` | One ban detail with a proof button. |
| `check_warns:<user>` and `check_warn_chat:` | Warnings by group. |
| `check_kicks:<user>:<page>` | Kick history. |
| `check_mutes:<user>:<page>` | Mute history. |
| `check_appeals:<user>:<page>` | Appeal history. |

Detail callbacks carry a stable identifier so a tap from a stale page is
refused. Pagination uses `utils/pagination.py`.

Special cases: the bot itself is reported clean with a recognition note; the
Owner cannot be banned and is reported clean; staff targets are reported as
staff with no active ban. `/check` does not provide an appeal button because
it is a third-party lookup.

## Database impact

The views read `moderation_actions`, `moderation_messages`,
`moderation_appeals`, `warns_db`, `kicks_db`, `mutes_db`, `users_roles`, and
`users_cache`. Expired warnings and mutes are excluded at query time. All
reads use `db_call`; independent counts are gathered in parallel where safe.

## Logging and rendering

Profiles are rendered with `ban_info.build_ban_summary()` and
`ban_info.build_ban_detail()`, using the rich transport. User-facing wording
comes from the `checking` catalog domain. Failed reads log at warning level
with the target id and show a localized retry notice. No parse mode is
selected.

## Edge cases

- A lookup outage never renders an empty history that would claim zero
  records; it shows an error and keeps the keyboard for a re-tap.
- A stale callback is acknowledged and discarded rather than editing the wrong
  page.
- Active-ban reads use the same expiry condition as the active-bans view.

## Validation hints

Relevant tests include `tests/test_check_*.py`, `tests/test_checkme_owner.py`,
and `tests/test_formatter.py`.

```bash
uv run pytest tests/ -q -k check
```
