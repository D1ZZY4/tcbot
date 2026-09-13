# Workflow Overview

This page describes the user-visible flows in TCF Bot. For state constants,
factories, and callback details, see
[Workflow internals](../architecture/workflows.md).

## Moderation flows

| Flow | Entry commands | Permission | Scope | Notes |
|---|---|---|---|---|
| Ban | `/tcban`, `/tcb` | Developer+ | All connected groups | Requires inline reason and proof media; updates existing active ban instead of duplicating. |
| Unban | `/tcunban`, `/tcunb` | Developer+ | All connected groups | Direct command; resolves an active ban and removes it federation-wide. |
| Kick | `/tckick`, `/tck` | Tester+ | Current group only | Conversation asks for reason/proof; auto-demotes role holders before kicking. |
| Mute | `/tcmute`, `/tcm` | Tester+ | All connected groups | Optional duration token before reason, for example `7d`. |
| Unmute | `/tcunmute`, `/tcunm`, `/tcum` | Tester+ | All connected groups | Direct command; restores send permissions. |
| Warn | `/tcwarn`, `/tcw` | Tester+ | Current group warning history | Reason required; auto-ban at `WARN_LIMIT` (default 3) per group or when `FED_WARN_LIMIT` (env, default disabled) is crossed across all groups. |
| Unwarn | `/tcunwarn`, `/tcunw` | Tester+ | Current group warning history | Removes the newest warning. |
| Warn list | `/warns`, `/warnlist` | Tester+ | Current group warning history | Shows a user's warnings. |
| Reset warns | `/resetwarns`, `/clearwarns` | Tester+ | Current group warning history | Clears all warnings for a user in the chat. |

## Ban flow

```mermaid
flowchart TD
    A[Admin sends /tcban target reason] --> B{Permission and target valid?}
    B -- No --> X[Reply with error and end]
    B -- Yes --> C{Active ban already exists?}
    C -- Yes --> D[Show update-confirm card with Continue / Cancel]
    D -- Cancel --> X
    D -- Continue --> E
    C -- No --> E{Target has a federation role?}
    E -- Yes --> F[Auto-demote target before banning]
    E -- No --> G[Prompt for proof]
    F --> G
    G --> H[Admin sends photos, videos, GIFs, or files]
    H --> I{Done button, silence flush, or 60 s cap}
    I --> J[Upload proof to proof destination]
    J --> K[Create or update ban record]
    K --> L[Post federation log]
    L --> M[fan_out ban across connected groups]
    M --> N[Edit prompt summary + DM appeal link]
```

Ban proof supports Telegram media albums as well as sequential sends: photos, videos, GIFs, and files accumulate in one proof session flushed by `Done`, `ALBUM_DEBOUNCE_SECONDS` of silence, or a 60 s cap.

## Reason + proof flows

Kick, mute, and warn use the shared `reason_flow.build_modaction_conv()` factory.

```mermaid
flowchart TD
    A[Command entry] --> B{Inline reason exists?}
    B -- Yes --> C[Prompt for proof]
    B -- No --> D[Prompt for reason]
    D --> E{Reason action}
    E -- Text --> C
    E -- Skip, if allowed --> C
    E -- Cancel --> Z[End]
    C --> F{Proof action}
    F -- Photo/video --> G[Record proof description and execute]
    F -- Skip, if allowed --> G
    F -- Cancel --> Z
    G --> Y[Reply/log result and end]
```

Warns configure `BuildReason("warn", skip_allowed=False)`, so a reason cannot be skipped.

## Appeal flow

Appeals start from a deep link: `/start appeal_<ban_id>` in bot PM.

```mermaid
flowchart TD
    A[User opens appeal deep link in PM] --> B{Active ban and ban ID match?}
    B -- No --> X[Explain why appeal cannot start]
    B -- Yes --> C[Show appeal instructions]
    C --> D[User sends #appeal text]
    D --> E{Starts with #appeal and references the ban log message ID?}
    E -- No --> C
    E -- Yes --> F[Forward appeal and post review card]
    F --> G[Staff taps Approve or Reject]
    G --> H{Decision}
    H -- Approve --> I[Unban across connected groups and notify user]
    H -- Reject --> J[Mark reviewed and notify user]
```

Required appeal sections:

```text
#appeal
Log link: https://t.me/...
Clarification: explanation of the situation
Agreement: commitment to follow community rules
```

The original banning admin has a 12-hour priority review window. During that window only the banning admin (`admin_user_id` on the ban) can act; other reviewers see the pending-review card. After the window, any Founder or Admin (effective role) can review the appeal. When the ban record carries no usable banning admin (missing or zero `admin_user_id`), the window does not apply. A review card left pending for more than 72 hours is cleared so the user can submit a fresh appeal, and a rejected appeal cannot be re-submitted for 24 hours.

## Group connection flow

```mermaid
flowchart TD
    A{Bot added to a group or /tcconnect used?}
    A -- /tcconnect --> B{Caller is an admin of the group?}
    B -- No --> X[Reply with error and end]
    B -- Yes --> C{Bot has required admin permissions?}
    C -- No --> D[Show required permissions and end]
    C -- Yes --> E[Complete connection]
    A -- Bot added --> F{Pending request and bot is admin?}
    F -- Yes --> E
    F -- No --> G[Show Connect / Cancel prompt]
    G -- Cancel --> H[Remove pending request, log rejection, leave chat]
    G -- Connect --> C
    E --> I[Apply existing federation bans and active mutes]
    I --> J[Mark group active and log connection]
```

Disconnected groups are marked inactive rather than deleted, preserving historical data.

## Staff role flows

- `/tcpromote` assigns `admin`, `developer`, or `tester` based on executor rank.
- Founder can assign Admin, Developer, or Tester.
- Admin can assign Developer or Tester directly.
- Admin-to-Admin promotion creates a queued request for Founder approval.
- `/tcpromoterequests` (`/tcreqs`) submits a promotion request; `/tcpromotelist` (`/tcplist`) lists pending requests.
- `/tcdemote` uses confirm/cancel buttons before removing a role.
- `/transferowner` transfers Founder ownership.

## Statistics and lookup flows

- `/checkme` (`/cme`) shows the caller's active ban status and appeal/proof buttons when applicable.
- `/check` (`/c`) lets anyone inspect a user's full federation profile (identity, role, bans, warnings, kicks, mutes, appeals).
- `/tcgroups` (`/tcg`) lists connected groups with a details toggle.
- `/tcstats` (`/tcs`) shows summary cards, active bans, connected chats, and search/detail views.
- `/tcsync` (`/tcsynchronize`) reconciles group membership against active bans and mutes, bounded at 200 checks per run.

## Maintenance and broadcast flows

- `/tcbroadcast` sends a message to every active connected group through bounded fan-out and logs success/failure counts.
- Staff-only `/cleanup` (aliases `/tcclean`, `/tcc`) checks active groups and
  deactivates groups the bot can no longer access.
- `/leaveall`, `/exitall`, and `/tcleave` are Founder-only emergency commands that make the bot leave connected groups and mark them inactive.
