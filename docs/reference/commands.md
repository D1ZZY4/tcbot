# Commands

This page lists every command, its aliases, access tier, and allowed origin.
Commands are matched by `build_prefixed_filters()` against all configured
prefixes (`/`, `!`, and `.` by default), so each alias works with every prefix.
Callback-only panels are listed at the end.

## Moderation

| Module | Commands | Access | Origin |
|---|---|---|---|
| `bans.py` | `/tcban`, `/tcb` | Developer and above | Bot DM, connected or primary group. |
| `unban.py` | `/tcunban`, `/tcunb` | Developer and above | Bot DM, connected or primary group. |
| `kick.py` | `/tckick`, `/tck` | Moderator and above | Connected or primary group. |
| `mute.py` | `/tcmute`, `/tcm`, `/tcunmute`, `/tcunm`, `/tcum` | Moderator and above | Connected or primary group. |
| `warns.py` | `/tcwarn`, `/tcw`, `/tcunwarn`, `/tcunw`, `/warns`, `/warnlist`, `/resetwarns`, `/clearwarns` | Moderator and above | Connected or primary group for writes; history is read-only. |
| `check.py` | `/check`, `/c`, `/checkme`, `/cme` | Anyone | Any chat. |
| `appeals.py` | `/start appeal_<ref>` deep link, `#appeal` in the main group, appeal review callbacks | Banned member or staff reviewer | Deep link is private; group tag requires the primary group. |

## Groups

| Module | Commands | Access | Origin |
|---|---|---|---|
| `connect.py` | `/tcconnect`, `/tccon`, plus `MY_CHAT_MEMBER` events | Group administrator; event driven | Group only. |
| `disconnecting.py` | `/tcdisconnect`, `/rmtc` | Group creator or federation staff | In-group or numeric chat id. |
| `groups.py` | `/tcgroups`, `/tcg` | Anyone | Bot DM or group. |

## Roles

| Module | Commands | Access |
|---|---|---|
| `admins.py` | `/tcpromote`, `/tcp`, `/tcdemote`, `/tcd`, `/transferowner`, `/tfowner`, `/tcpromoterequests`, `/tcreqs`, `/tcpromotelist`, `/tcplist` | Staff and Owner. |
| `admins.py` | `promo_approve:*`, `promo_reject:*`, `promo_role:*`, `demote_confirm:*` callbacks | Owner for approvals; staff for prompts. |

## Information and utilities

| Module | Commands | Access |
|---|---|---|
| `language.py` | `/language`, `/lang`, `/langs`, language callbacks | Anyone; group scope requires manage rights. |
| `rules.py` | `/tcrules`, `/rules`, rule callbacks | Staff editor and public reader. |
| `stats.py` | `/tcstats`, `/tcs`, stats callbacks | Anyone; drill-downs check rank. |
| `start.py` | `/start`, main-menu callbacks | Anyone. |
| `help.py` | `/help`, help callbacks | Anyone. |
| `about.py` | `about_menu` callback | Anyone. |
| `additional.py` | `additional_menu` callback | Anyone. |
| `privacy.py` | privacy callbacks | Anyone. |
| `greeting.py` | New-member, join-request, left-member, and migration events | Event driven. |

## Operator tools

| Module | Commands | Access |
|---|---|---|
| `broadcast.py` | `/tcbroadcast`, `/bc` | Staff. |
| `maintenance.py` | `/tcleaveall`, `/leaveall`, `/exitall`, `/cleanup`, `/tcclean`, `/tcc`, `/tcforget`, `/tcf`, `/tcrepair`, `/tcr` | Staff and Owner. |
| `netspeed.py` | `/ping`, `/p`, `/speedtest`, `/st` | Owner. |

## Handler conventions

- Decorator order is `ratelimiter()` outermost, the required authorization guard
  second, and `log_execution` innermost. Message-event handlers are exempt from
  per-handler rate limits.
- Callback handlers answer `q.answer()` before visible work.
- Multi-step actions run in a `ConversationHandler` under
  `modules/helper/pipelines/`, registered per chat and per user.
- Every callback payload and conversation state is listed in
  [Callbacks and states](callbacks.md).

The authoritative command ownership table for developers is in
[Architecture overview](../architecture/overview.md#module-discovery-and-registration).
