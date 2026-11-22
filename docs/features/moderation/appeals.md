# Appeals

This page describes appeal submission and staff review as implemented by
`tcbot/modules/appeals.py` and the appeal flows in `helper/pipelines/`.
Submission, review windows, and decisions are drawn in
[the appeals diagram](../../pipelines/appeals.md).

Related pages: [banning](banning.md), [unbanning](unbanning.md), and
[language](../language.md).

## Purpose and ownership

An appeal lets an actively banned user ask for the ban to be lifted. Submission
happens in the bot DM through a deep link, or by posting `#appeal` in the main
group. A staff member decides on a review card. Approval is an irreversible
federation unban and may also demote a staff target, so every path is guarded
and committed atomically.

Ownership: `appeals.py` registers the entries; `appeal_submit_flow.py` owns
submission; `appeal_review_flow.py` owns staff decisions;
`bans_db/_writes.py` and `_lifecycle.py` own the atomic claim and verdict;
`notification_worker.py` closes cards whose direct edit failed.

## Entry points

| Entry | Handler | Gate |
|---|---|---|
| Private deep link `/start appeal_<ref>` | `appeal.build_handler()` | Private chat, active ban owned by the sender. |
| `#appeal` in the main group | `on_group_appeal` | `cfg.is_primary_group()`, then the sender's active ban. |
| Staff decision | `on_appeal_decision` | `THROTTLE_STAFF`, then the review flow. |

`REF_PATTERN` is `[a-z0-9]{10,32}` so imported legacy decisions with longer
references still work. `#appeal` matching is case-insensitive. The group path
stores `appeal_ban_id` and `appeal_log_msg_id` in the flow scope and delegates
to the same submit mixin used by the DM path.

## Submission flow

`WAITING_APPEAL` awaits a message starting with `#appeal`. Text over 2000
characters gets a "too long" reply and stays in the state. The instruction
prompt carries a cancel button; its message id is kept as
`appeal_instruction_msg_id` and used for the live-card guard.

The submit sequence forwards the original appeal message to `cfg.appeals`,
posts a review card in the main group, posts a copy in `cfg.appeals`, sends the
initial log to `cfg.logs`, attaches the review keyboard only after the card id
is known, and finally claims the review slot with
`bans_db.submit_appeal(ban_id, user_id, text, review_message_id)` in one
transaction. Only the claim winner keeps the cards; a loser deletes them and
sees a "pending review" reply. Cancellation is preserved across the parallel
posts.

The review keyboard emits `appeal_approve_<ban_id>_<review_message_id>` and
`appeal_reject_<ban_id>_<review_message_id>` with success and danger styles.

## Time windows and slots

| Window | Value | Effect |
|---|---|---|
| Reviewer lock | 12 hours | A non-actor reviewer is blocked while the lock is active. The original ban actor is not. |
| Stale review | 72 hours | A stale review slot may be released for a new submission. |
| Rejection cooldown | 24 hours | A rejected appellant cannot resubmit inside the window. |
| Appeal deadline | Ban `expires_at` | A timed ban past its deadline cannot be decided. |
| Maximum text | 2000 characters | Longer text stays in `WAITING_APPEAL`. |

A review slot lives in ban metadata as `review_message_id` and
`review_timestamp`. Helpers claim, consume, restore, and release it only under
the matching conditions, so one decision owns one card.

## Staff decision path

A decision tap is answered per branch, never up front: Telegram accepts one
answer, so an early ack would swallow refusal alerts. The flow re-reads the
caller's role, rejects non-staff, verifies the ban is still active and
undecided, checks that the tapped card is the live one, applies the reviewer
lock, and refuses self-decisions. `claim_appeal_decision()` runs before the
verdict write so a concurrent tap race has a single winner.

Approval:

1. Read the target's fresh role and first name in parallel. A failed lookup
   ends with a database-retry alert and no decision.
2. `guards.outranks()` prevents an Admin from deciding against a peer Admin.
3. Build the chat list from `active_groups()` plus the primary group.
4. A staff target first passes `demote_before_unban(trigger="appeal")`, which
   fails closed.
5. `approve_appeal_and_queue_unban()` commits the acceptance, revokes the ban,
   drops the review keys, and queues a `revoke:appeal:v1` run in one
   transaction.
6. `enforcement_worker.deliver_queued_run()` lifts the restriction now.
7. Four independent notifications are gathered: the target DM, the card edit,
   the edited log, and a separate unban log.

Rejection repeats the fresh role and outrank checks, then calls
`reject_appeal()`. On success it edits the card, sends the target DM, and edits
the appeal log. A path ending without a decision restores the review slot and
never masks cancellation.

## Database impact

Decision helpers write `moderation_appeals`, update `moderation_actions`
status and metadata, and insert `moderation_enforcement_runs` and
`moderation_notification_tasks` rows. The approval transaction rolls back
whole if the ban cannot be revoked, so an accepted appeal never sits on an
active ban. The atomic claim and slot helpers live in `bans_db/_writes.py`.

## Logging and durable card edits

`messages.appeal_received_log`, `appeal_submitted_log`, `appeal_approved_edit`,
`appeal_rejected_edit`, and `appeal_unban_log` build the staff-facing posts.
When a direct card edit fails, `notifications_db.enqueue_review_card_edit()`
records it. `notification_worker.py` claims due tasks, skips cards that are
still live, and retries up to five times at five-minute intervals. A card that
is still the live review of an active decision with a pending appeal is never
closed.

## Edge cases

- A legacy card without a review id falls back to the tapped message id, so a
  replaced card is still refused by the live-card check.
- A link for an inactive ban, a different account, or an undecidable timed ban
  is refused.
- A failed card edit does not fail the decision; the outbox owns the retry.
- An OPEN Telegram circuit pauses the notification worker so retry budgets are
  preserved.

## Validation hints

Relevant tests include `tests/test_appeal_*.py` and
`tests/test_notification_worker.py`.

```bash
uv run pytest tests/ -q -k appeal
```
