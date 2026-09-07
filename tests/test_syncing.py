# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Enforcement reconciliation: pair bounding plus outcome classification."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, cast

from telegram.constants import ChatMemberStatus
from telegram.error import BadRequest

from tcbot.modules import syncing as sy


def _run(coro: Any) -> Any:
    """Drive one coroutine to completion without a pytest async plugin."""
    return asyncio.run(coro)


class _FakeBot:
    """Duck-typed bot: scripted memberships plus enforced-action ledger."""

    def __init__(self, members: dict[tuple[int, int], Any]) -> None:
        self._members = members
        self.banned: list[tuple[int, int]] = []
        self.unbanned: list[tuple[int, int]] = []

    async def get_chat_member(self, chat_id: int, user_id: int) -> Any:
        key = (chat_id, user_id)
        if key not in self._members:
            raise BadRequest("USER_NOT_PARTICIPANT")
        result = self._members[key]
        if isinstance(result, BaseException):
            raise result
        return SimpleNamespace(status=result, user=SimpleNamespace(id=user_id))

    async def ban_chat_member(self, chat_id: int, user_id: int) -> bool:
        self.banned.append((chat_id, user_id))
        return True

    async def unban_chat_member(
        self, chat_id: int, user_id: int, *, only_if_banned: bool = True
    ) -> bool:
        self.unbanned.append((chat_id, user_id))
        return True


def test_take_pairs_bounds_and_flags_truncation() -> None:
    pairs, truncated = sy.take_pairs([1, 2], [10, 20, 30], 4)
    assert pairs == [(1, 10), (1, 20), (1, 30), (2, 10)]
    assert truncated is True


def test_take_pairs_without_truncation() -> None:
    pairs, truncated = sy.take_pairs([1], [10], 200)
    assert pairs == [(1, 10)]
    assert truncated is False


def test_ban_pair_enforces_present_member() -> None:
    bot = _FakeBot({(5, 9): ChatMemberStatus.MEMBER})
    assert _run(sy._sync_ban_pair(cast("Any", bot), 5, 9)) == "enforced"
    assert bot.banned == [(5, 9)]


def test_ban_pair_skips_kicked_absent_privileged() -> None:
    bot = _FakeBot(
        {
            (5, 1): ChatMemberStatus.BANNED,
            (5, 3): ChatMemberStatus.ADMINISTRATOR,
        }
    )
    assert _run(sy._sync_ban_pair(cast("Any", bot), 5, 1)) == "ok"
    assert _run(sy._sync_ban_pair(cast("Any", bot), 5, 2)) == "absent"
    assert _run(sy._sync_ban_pair(cast("Any", bot), 5, 3)) == "privileged"
    assert bot.banned == []


def test_ban_pair_reports_unexpected_errors() -> None:
    bot = _FakeBot({(5, 9): ValueError("boom")})
    assert _run(sy._sync_ban_pair(cast("Any", bot), 5, 9)) == "error"
    assert bot.banned == []


def test_unban_pair_clears_stale_kick_only() -> None:
    bot = _FakeBot(
        {
            (5, 1): ChatMemberStatus.BANNED,
            (5, 2): ChatMemberStatus.MEMBER,
        }
    )
    assert _run(sy._sync_unban_pair(cast("Any", bot), 5, 1)) == "unenforced"
    assert _run(sy._sync_unban_pair(cast("Any", bot), 5, 2)) == "ok"
    assert _run(sy._sync_unban_pair(cast("Any", bot), 5, 3)) == "absent"
    assert bot.unbanned == [(5, 1)]


def test_summarize_counts_and_samples_titles() -> None:
    pairs = [(9, 5), (9, 6), (9, 7), (9, 8)]
    outcomes: list = ["enforced", "ok", ValueError("x"), "privileged"]
    counts, _ = sy._summarize(
        pairs, outcomes, {5: "A", 6: "B", 7: "C", 8: "D"}, truncated=True
    )
    assert (counts.checked, counts.enforced_bans, counts.skipped, counts.failed) == (
        4,
        1,
        2,
        1,
    )
    assert counts.truncated is True
    assert counts.failed_titles == ("C",)


def test_render_summary_names_failures() -> None:
    counts = sy.SyncCounts(
        checked=10, enforced_bans=2, skipped=7, failed=1, failed_titles=("Grp",)
    )
    text = sy._render_summary(counts, target="federation sweep")
    assert "Grp" in text and "2" in text
