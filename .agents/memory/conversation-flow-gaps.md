---
name: Conversation flow gaps (reason_flow / ban_flow)
description: Known unfixed gaps in moderation ConversationHandler flows - album duplicate-processing and double-submit races. Not yet fixed as of session 189 (2026-07-09).
---

## Album/media-group duplicate processing in reason_flow.py

`ban_flow.py` accumulates album/media-group proof photos via an async flush
mechanism (`_flush_album`) before triggering the executor once. `reason_flow.py`
(shared by kicking_flow, muting_flow, warning_flow) does not: its proof handler
processes each photo in an album as a separate update, so a moderator sending
a 3-photo album can trigger the kick/mute/warn executor 3 times for one event
(duplicate DB records, duplicate log-channel messages).

**Why not fixed yet:** requires porting `ban_flow.py`'s accumulator pattern into
the shared `reason_flow.py`, which is used by three other flows - a
non-trivial, testable-in-isolation change, not a one-line fix. Deferred to a
future session with room to add flow-level tests.

## Double-submit races (all six *_flow.py modules)

No flow sets a "busy"/in-flight flag in `ctx.user_data` at the start of its
executor entry point. Rapid double-submission (e.g. clicking "Skip" twice, or
sending proof then immediately clicking Skip) can invoke the executor twice
before the first call completes and clears conversation state.

**Why not fixed yet:** same reasoning - a real but low-frequency race (requires
two taps within one event-loop tick), best fixed with a shared decorator or
helper across all six flows rather than six one-off patches.

**How to apply:** when next touching any `*_flow.py` executor, add an
`ctx.user_data["<action>_executing"]` guard checked/set atomically at entry,
and for `reason_flow.py`, port `ban_flow.py`'s `_flush_album` pattern.
