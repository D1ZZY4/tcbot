---
name: ConversationHandler test patterns
description: Non-obvious mocking rules discovered when writing offline state-machine tests for ban_flow, warning_flow, and appeal_flow.
---

## Album accumulator cleanup
`ban_flow._albums` and `ban_flow._album_meta` are module-level dicts. Tests that exercise the album path must clear them before and after to prevent cross-test leakage.

**Why:** pytest collects all tests in one process; leftover album state from one test silently poisons the next.

**How to apply:** `ban_flow._albums.clear(); ban_flow._album_meta.clear()` at start and end of album tests. Also monkeypatch `ban_flow._flush_album` to `AsyncMock()` so `asyncio.create_task` schedules a task that resolves immediately instead of sleeping `cfg.album_debounce` seconds.

## asyncio.gather return shape for on_decision
`appeal_flow.BuildAppeal.on_decision` uses `asyncio.gather(q.answer(), db.bans_db.get_ban(ban_id))` without `return_exceptions=True`. Both mocks must succeed; the unpacking is `_, ban = result`.

**Why:** A gather without `return_exceptions` propagates the first exception, so a raising mock would skip the ban-check assertions entirely.

## bot.ban_chat_member / unban_chat_member under mocked fan_out
When `fan_out` is monkeypatched, the list comprehension `[bot.ban_chat_member(g, tid) for g in groups]` still calls `ban_chat_member` to build the list. Use `Mock()` (not `AsyncMock()`) so the call returns a plain object rather than an unawaited coroutine, avoiding `PytestUnraisableExceptionWarning`.

**How to apply:** `bot = SimpleNamespace(ban_chat_member=Mock(), ...)` whenever `fan_out` is mocked.

## _start / _on_entry separation
`_on_entry` only parses the `/start appeal_<id>` regex and delegates to `_start`. To test `_on_entry` end-to-end without mocking the private method, let `_start` run with a controlled DB mock (e.g., `get_ban` returns None to trigger the "invalid" path quickly).

## ruff I001 import order
Imports `from tcbot.modules.helper.workflows import appeal_flow` and `from tcbot.modules.helper.workflows.appeal_flow import ...` in the same block trigger I001. Fix with `uvx ruff check --fix .` rather than manual reordering.
