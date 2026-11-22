# Banning

This page describes the federation ban as implemented by `tcbot/modules/bans.py`,
the flows in `helper/pipelines/ban_flow.py`, and the helpers in
`tcbot/database/bans_db/`. It covers commands, the conversation, persistence,
logging, and edge cases. The state machine and full system spine are drawn in
[the banning diagram](../../pipelines/banning.md).

Related pages: [unbanning](unbanning.md), [appeals](appeals.md),
[check](check.md), [warnings](warnings.md), and
[roles](../roles/roles.md).

## Purpose and ownership

A federation ban records a `ban` decision in `moderation_actions` and applies
a Telegram ban across all active connected groups plus the primary groups. A
ban requires a reason and landed proof, archives every uploaded item, posts a
federation log with an appeal deep link, and queues durable enforcement.
Proof and log message IDs, the appeal link, and the review slot are part of
the decision document.

Ownership: the command entry lives in `bans.py`; the conversation and executor
live in `ban_flow.py`, `ban_confirmation.py`, and `ban_rules_step.py`; proof
collection lives in `proof_flow.py` and `proof_session.py`; durable delivery
lives in `enforcement_worker.py`; persistence lives in `bans_db/` and
`moderation_db.py`.

## Commands and access

| Command | Alias | Access | Origin |
|---|---|---|---|
| `/tcban <target> <reason>` | `/tcb` | Developer and above (`mod_only`) | Bot DM or a connected or primary group. |

The handler uses `ratelimiter(THROTTLE_FEDERATION)` outermost, then `mod_only`,
then `log_execution`. A disconnected group is refused, and a connection-state
outage blocks the action rather than letting a non-federation chat drive
federation-wide enforcement.

Targets resolve by reply, numeric ID, or `@username`. A typed ID or username
that verifies as a real user different from the quoted sender overrides the
reply; a restated ID naming the quoted user is dropped from the reason. A
reason is required and shares the common 1000-character cap. Overlong inline
reasons fail fast before any role lookup.

## Conversation and callbacks

The ban flow has these states and callbacks:

| State | Value | Meaning |
|---|---|---|
| `WAITING_PROOF` | 0 | Collecting proof media. |
| `WAITING_UPDATE_CONFIRM` | 1 | Confirming a re-ban of an active ban. |
| `WAITING_BAN_RULES` | 2 | Picking published rules to cite. |
| `WAITING_BAN_RULES_NOTE` | 3 | Entering an optional rules note. |

| Callback | Effect |
|---|---|
| `ban_continue` | Continue a re-ban from a live prompt. |
| `ban_cancel` | Cancel the prompt. |
| `ban_done_proof` | Flush collected proof now. |
| `rules_step:pick:<id>` | Toggle a published rule item. |
| `rules_step:done` | Accept the selection and continue. |
| `rules_step:other` | Enter a note. |
| `rules_step:clear` | Clear the selection. |

The rules picker is skipped when no rules are published or the moderator lacks
`rules.view`. The re-ban confirmation shows existing and new reasons plus
`View Log` and `View Proof` links. Prompt freshness is checked with
`scope.callback_is_current()`, so a tap from an older prompt is discarded.

## Proof and enforcement

Proof accepts photos, videos, animations, and documents. It is mandatory for a
ban (`BuildProof("ban", skip_allowed=False)`), so there is no Skip button. The
session is keyed by `(chat_id, user_id)` and flushes on Done, after
`cfg.album_debounce` seconds of silence, or at the 60-second cap. Photos and
videos upload as media groups of at most ten; animations and documents send
individually. Every landed item is archived with its real media type.

The executor gate runs twice: once before proof upload and record write, and
again immediately before the decision is written. Both use
`guards.enforcement_refusal(min_role="developer")`. A refusal edits the prompt
and leaves no record, proof, or fan-out behind. `demote_before_enforcement(trigger="ban")`
then removes a federation role held by the target on a best-effort basis.

The scope merges connected groups, the configured primary group, and the
originating group. A ban from bot PM has only the primary group. A failed
group-list fetch still enforces at the origin and marks the summary with a
scope warning.

## Database impact

One `moderation_actions` row with `action_type = 'ban'` and
`scope_type = 'community'`. Key written fields: `ban_id` (the appeal token),
`target_user_id`, `reason`, `actor_user_id`, `status`, `case_id`,
`evidence_upload_id`, `action_origin`, and `metadata`. The message IDs come
from `moderation_messages`, the appeal fields from `moderation_appeals`, and
the review slot from decision metadata.

The decision, its case, evidence archive, rule links, and the `apply`
enforcement run commit in one transaction with idempotency key
`moderation:{action_id}:apply:v1`. The Telegram log post and fan-out happen
only after the commit. A partial unique index permits one active ban per
target; a concurrent loser reuses or supersedes the canonical record.

## Logging and notifications

`messages.ban_log()` and `messages.ban_update_log()` build the federation log
posted to `cfg.logs` through `send_log`. The keyboard carries a proof link and
an appeal deep link built by `links.appeal_deep_link()`. The moderator's prompt
is edited in place with the applied, failed, and pending counts from
`delivery_outcome()`. The target receives a DM with the same deep link; a
`Forbidden` there is expected.

The proof caption uses `proof_caption_new` for a new ban and
`proof_caption_update` for a re-ban. Audit and proof builders live in
`messages/audit_logs.py`; button builders live in `buttons/ban.py`.

## Edge cases

- An active-ban lookup failure fails closed with the database retry notice and
  clears the flow scope instead of starting a proof round that would abort.
- A new ban with partial or missing proof is refused before any record is
  written. A re-ban may carry the full previous evidence batch forward.
- A failed group ban is recorded per target and retried; it does not roll back
  the decision. A group that refused because the bot lost rights is a
  permanent failure and stays visible for operator repair.
- A timed decision that expired while its run waited is cancelled rather than
  served late.
- The demote step is best effort: a role-lookup failure is logged and ban
  enforcement still runs.
- The proof conversation is per chat and per user, so simultaneous flows stay
  isolated.

## Validation hints

Relevant tests include `tests/test_ban_*.py`, `tests/test_proof_items.py`, and
`tests/test_enforcement_worker.py`. Run the focused set with:

```bash
uv run pytest tests/ -q -k ban
```
