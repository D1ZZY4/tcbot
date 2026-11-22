# Flow overview

This page is the human-oriented map of user-visible flows. It summarizes what
a member, moderator, or operator sees and links to the detailed pages. No
diagrams live here; the complete diagrams are under [pipelines](../pipelines/banning.md).

## Moderation at a glance

| Flow | Command | Entry access | Detailed page |
|---|---|---|---|
| Federation ban | `/tcban` | Developer and above | [Banning](moderation/banning.md) |
| Group kick | `/tckick` | Moderator and above | [Kicking](moderation/kicking.md) |
| Timed or permanent mute | `/tcmute` | Moderator and above | [Muting](moderation/muting.md) |
| Warning | `/tcwarn` | Moderator and above | [Warnings](moderation/warnings.md) |
| Unban | `/tcunban` | Developer and above | [Unbanning](moderation/unbanning.md) |
| Appeal | `/start appeal_<ref>`, `#appeal` | Banned member, staff reviewer | [Appeals](moderation/appeals.md) |
| Self status | `/checkme` | Anyone | [Check](moderation/check.md) |
| User profile | `/check` | Anyone | [Check](moderation/check.md) |

The shared moderation conversation collects a reason, optionally lets the
moderator cite published rules, then collects proof. Ban requires proof; kick,
mute, and warn allow Skip. Done and Skip claim an execution flag before the
first await so a double tap cannot enforce twice. See
[proof](../pipelines/proof.md).

Every moderation action rechecks the executor's rank after the proof window
and before the write. A target who holds a federation role is demoted first.
Ban, kick, and mute demote on a best-effort basis; unban and appeal approval
fail closed. See [permissions](../pipelines/permissions.md).

## Group lifecycle

| Flow | Command | Entry access | Detailed page |
|---|---|---|---|
| Connect a group | `/tcconnect` or bot-added prompt | Group admin | [Connecting](moderation/connecting.md) |
| List connected groups | `/tcgroups` | Anyone | [Groups](moderation/groups.md) |
| Disconnect a group | `/tcdisconnect`, `/rmtc` | Group creator or staff | [Disconnecting](moderation/disconnecting.md) |

Connecting replays active bans and mutes into the new group and queues any
remainder. Join events re-check active decisions afterward. Primary groups are
infrastructure destinations and refuse connect, join decisions, and
disconnect. See [connection](../pipelines/connection.md).

## Roles and ownership

| Flow | Command | Entry access | Detailed page |
|---|---|---|---|
| Grant a role | `/tcpromote` | Staff | [Promote](roles/promote.md) |
| Review an Admin request | `promo_approve:*`, `promo_reject:*` | Owner | [Promote](roles/promote.md) |
| Remove a role | `/tcdemote` | Staff | [Demote](roles/demote.md) |
| Transfer ownership | `/transferowner` | Owner | [Roles](roles/roles.md) |

Only the Owner grants Admin directly. An Admin who targets Admin creates a
queued request. Ownership transfer is one atomic transaction under an advisory
lock, and the previous Owner becomes Admin in the same transaction. See
[roles](../pipelines/roles.md).

## Rules, language, and information

| Flow | Command | Entry access | Detailed page |
|---|---|---|---|
| Edit and publish rules | `/tcrules` | Staff with `rules.manage` | [Rules](moderation/rules.md) |
| Read rules | `/rules` | Anyone | [Rules](moderation/rules.md) |
| Set a locale | `/language` | Anyone | [Language](language.md) |
| View statistics | `/tcstats` | Anyone | [Statistics](statistics.md) |
| Help and menus | `/help`, `/start` | Anyone | [Miscellaneous modules](misc-modules.md) |

Rules publish to the main channel under a database lease. Members can
acknowledge the published version from the welcome message in the primary
group. Locale preferences are per user or per group and render every
user-facing message. See [rules](../pipelines/rules.md) and
[transport](../pipelines/transport.md).

## Operator flows

Maintenance commands (`/tcleaveall`, `/cleanup`, `/tcrepair`, `/tcforget`)
and network tools (`/ping`, `/speedtest`) are Owner or staff diagnostics. See
[Miscellaneous modules](misc-modules.md) and
[CI/CD](../operations/ci-cd.md).

## Delivery and durability

Database writes commit before Telegram calls. Multi-group enforcement uses the
bounded `fan_out()` dispatcher and the Telegram circuit breaker. Failed group
deliveries are retried by the enforcement worker, and failed review-card edits
are retried by the notification worker. See
[persistence](../pipelines/persistance.md) and
[rate limiting](../pipelines/ratelimit.md).

## Validation hints

`tests/test_flow_scope.py`, `tests/test_callback_freshness.py`, and the
per-domain `tests/test_*_flow.py` files cover the state transitions described
here.
