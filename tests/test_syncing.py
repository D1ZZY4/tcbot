# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Enforcement reconciliation: pair bounding plus outcome classification."""

from __future__ import annotations

import asyncio
import dataclasses
from types import SimpleNamespace
from typing import Any, cast

import pytest
from telegram.constants import ChatMemberStatus
from telegram.error import BadRequest

from tcbot import cfg
from tcbot import database as db
from tcbot.database.documents import GroupDoc
from tcbot.database.types import GroupId
from tcbot.modules import sync as sy
from tcbot.modules.helper.pipelines.demote_flow import Demote


def _run(coro: Any) -> Any:
    """Drive one coroutine to completion without a pytest async plugin."""
    return asyncio.run(coro)


class _FakeBot:
    """Duck-typed bot: scripted memberships plus enforced-action ledger."""

    def __init__(self, members: dict[tuple[int, int], Any]) -> None:
        self._members = members
        self.banned: list[tuple[int, int]] = []
        self.unbanned: list[tuple[int, int]] = []
        self.restricted: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

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

    async def restrict_chat_member(self, *args: Any, **kwargs: Any) -> bool:
        self.restricted.append((args, kwargs))
        return True

    async def unban_chat_member(
        self, chat_id: int, user_id: int, *, only_if_banned: bool = True
    ) -> bool:
        self.unbanned.append((chat_id, user_id))
        return True


def test_take_pairs_bounds_and_flags_truncation() -> None:
    pairs, truncated, _ = sy.take_pairs([1, 2], [10, 20, 30], 4)
    # * User-major order: every chat carries the same number of pairs, so
    # * no chat is loaded past the per-chat Telegram limit while others
    # * stay untouched.
    assert pairs == [(1, 10), (1, 20), (1, 30), (2, 10)]
    assert truncated is True


def test_take_pairs_spreads_the_sweep_across_the_chats() -> None:
    """Every chat must carry the same share of the checked pairs.

    Telegram admits 20 requests a minute per chat, so a sweep that loaded
    one chat with every user would exceed the per-chat budget and time out
    the requests that queue behind it.
    """
    user_ids = list(range(1, 51))
    chat_ids = [10, 20, 30, 40, 50]
    pairs, _, _ = sy.take_pairs(user_ids, chat_ids, 200)

    per_chat: dict[int, int] = {}
    for _, chat_id in pairs:
        per_chat[chat_id] = per_chat.get(chat_id, 0) + 1

    assert len(per_chat) == len(chat_ids)
    assert max(per_chat.values()) == min(per_chat.values())


def test_take_pairs_without_truncation() -> None:
    pairs, truncated, _ = sy.take_pairs([1], [10], 200)
    assert pairs == [(1, 10)]
    assert truncated is False


def test_take_pairs_caps_the_load_on_one_chat() -> None:
    """No chat may carry more pairs than the per-chat Telegram budget.

    Each pair costs up to two requests and Telegram admits 20 a minute per
    chat, so an uncapped sweep queued every probe behind the rate limiter
    and the queued probes were cancelled by their own timeout.
    """
    user_ids = list(range(1, 51))
    pairs, truncated, _ = sy.take_pairs(user_ids, [10], 200)

    per_chat: dict[int, int] = {}
    for _, chat_id in pairs:
        per_chat[chat_id] = per_chat.get(chat_id, 0) + 1

    assert max(per_chat.values()) <= sy._SYNC_MAX_PAIRS_PER_CHAT
    assert truncated is True


def test_take_pairs_offset_rotates_the_users() -> None:
    """A later sweep must cover the users the cap left out."""
    user_ids = list(range(1, 21))
    first, _, _ = sy.take_pairs(user_ids, [10], 200)
    second, _, _ = sy.take_pairs(user_ids, [10], 200, offset=10)

    first_users = {uid for uid, _ in first}
    second_users = {uid for uid, _ in second}

    assert first_users != second_users
    assert first_users.isdisjoint(second_users)


def test_take_pairs_shares_one_budget_between_two_passes() -> None:
    """The ban and mute passes must not each spend the per-chat budget.

    Both passes hit the same chats, so a group must not receive twice the
    per-chat allowance.
    """
    used: dict[int, int] = {}
    ban_pairs, _, _ = sy.take_pairs([1, 2, 3, 4], [10], 200, used=used)
    mute_pairs, _, _ = sy.take_pairs([5, 6, 7, 8], [10], 200, used=used)

    total = len(ban_pairs) + len(mute_pairs)
    assert total <= sy._SYNC_MAX_PAIRS_PER_CHAT
    assert used[10] == total


def test_take_pairs_reports_the_covered_user_count() -> None:
    """The sweep cursor advances by the users the run actually covered."""
    _, _, covered = sy.take_pairs([1, 2, 3], [10, 20], 200)
    assert covered == 3


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


def test_mute_pair_restricts_present_member() -> None:
    bot = _FakeBot({(5, 9): ChatMemberStatus.MEMBER})
    assert _run(sy._sync_mute_pair(cast("Any", bot), 5, 9)) == "remuted"
    assert len(bot.restricted) == 1
    assert bot.restricted[0][0][:2] == (5, 9)


def test_mute_pair_skips_restricted_banned_absent_privileged() -> None:
    bot = _FakeBot(
        {
            (5, 1): ChatMemberStatus.RESTRICTED,
            (5, 2): ChatMemberStatus.BANNED,
            (5, 4): ChatMemberStatus.ADMINISTRATOR,
        }
    )
    assert _run(sy._sync_mute_pair(cast("Any", bot), 5, 1)) == "ok"
    assert _run(sy._sync_mute_pair(cast("Any", bot), 5, 2)) == "ok"
    assert _run(sy._sync_mute_pair(cast("Any", bot), 5, 3)) == "absent"
    assert _run(sy._sync_mute_pair(cast("Any", bot), 5, 4)) == "privileged"
    assert bot.restricted == []


def test_mute_pair_reports_unexpected_errors() -> None:
    bot = _FakeBot({(5, 9): ValueError("boom")})
    assert _run(sy._sync_mute_pair(cast("Any", bot), 5, 9)) == "error"
    assert bot.restricted == []


def test_summarize_counts_remuted() -> None:
    pairs = [(9, 5), (9, 6)]
    counts, _ = sy._summarize(
        pairs, ["remuted", "ok"], {5: "A", 6: "B"}, truncated=False
    )
    assert (counts.checked, counts.enforced_mutes, counts.skipped) == (2, 1, 1)


def test_demote_staff_holdings_strips_staff_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    roles = {9: "developer", 10: None, 11: "founder"}
    removed: list[int] = []

    async def _role(user_id: int, *, fresh: bool = False) -> str | None:
        return roles.get(user_id)

    async def _demote_remove(target_id: int, target_role: str) -> bool:
        removed.append(target_id)
        return True

    monkeypatch.setattr(db.users_roles, "get_effective_role", _role)
    monkeypatch.setattr(Demote, "remove_role", _demote_remove)
    _run(sy._demote_staff_holdings([9, 10, 11]))
    # * Only the developer holder is stripped.
    assert removed == [9]


def test_demote_staff_holdings_skips_outage(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _boom(user_id: int, *, fresh: bool = False) -> str | None:
        raise RuntimeError("db down")

    removed: list[int] = []

    async def _demote_remove(target_id: int, target_role: str) -> bool:
        removed.append(target_id)
        return True

    monkeypatch.setattr(db.users_roles, "get_effective_role", _boom)
    monkeypatch.setattr(Demote, "remove_role", _demote_remove)
    _run(sy._demote_staff_holdings([9]))
    assert removed == []


def test_enforcement_scope_covers_the_primary_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The primary group is enforced in, so sync must reconcile it as well."""
    monkeypatch.setattr(sy, "cfg", dataclasses.replace(cfg, main_group=-100))
    groups: list[GroupDoc] = [{"chat_id": GroupId(-1), "title": "Connected"}]
    chat_ids, titles = sy._enforcement_scope(groups)
    assert chat_ids == [-100, -1]
    assert titles[-1] == "Connected"


def test_enforcement_scope_leads_with_the_primary_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The primary group must stay inside the pair budget when the sweep truncates."""
    monkeypatch.setattr(sy, "cfg", dataclasses.replace(cfg, main_group=-100))
    groups: list[GroupDoc] = [
        {"chat_id": GroupId(-500), "title": "Other"},
        {"chat_id": GroupId(-900), "title": "Another"},
    ]
    chat_ids, _ = sy._enforcement_scope(groups)
    assert chat_ids == [-100, -900, -500]


def test_run_ban_sync_enforces_in_the_primary_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A ban is re-applied in the primary group even when it is not connected."""
    monkeypatch.setattr(sy, "cfg", dataclasses.replace(cfg, main_group=-100))

    async def _groups() -> list[dict[str, Any]]:
        return [{"chat_id": -1, "title": "Connected"}]

    async def _ban_ids() -> list[int]:
        return [9]

    async def _mute_docs() -> list[Any]:
        return []

    async def _role(user_id: int, *, fresh: bool = False) -> str | None:
        return None

    monkeypatch.setattr(db.groups_db, "active_groups", _groups)
    monkeypatch.setattr(db.bans_db, "active_ban_user_ids", _ban_ids)
    monkeypatch.setattr(db.mutes_db, "active_mute_docs", _mute_docs)
    monkeypatch.setattr(db.users_roles, "get_effective_role", _role)

    bot = _FakeBot(
        {
            (-1, 9): ChatMemberStatus.MEMBER,
            (-100, 9): ChatMemberStatus.MEMBER,
        }
    )
    counts = _run(sy.run_ban_sync(cast("Any", bot)))
    assert sorted(bot.banned) == [(-100, 9), (-1, 9)]
    assert counts.enforced_bans == 2
