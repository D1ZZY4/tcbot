# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Degraded /check drill-downs: DB failures render a view instead of raising."""

from __future__ import annotations

import asyncio

import pytest

from tcbot import database as db
from tcbot.modules import check
from tcbot.modules.helper.pipelines import check_panels
from tcbot.utils.i18n import Safe, code, t, user_ref


def _expected_not_found(ban_id: str) -> str:
    return t("checking.bans.not_found", None, ban=Safe(code(ban_id)))


def _expected_db_fail(ban_id: str) -> str:
    return t("checking.bans.db_fail", None, ban=Safe(code(ban_id)))


async def _fake_name(uid: int) -> str:
    return "Alice"


def test_ban_detail_db_failure_renders_retry_card(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _boom(ban_id: str) -> object:
        raise RuntimeError("db blip")

    monkeypatch.setattr(db.bans_db, "get_ban", _boom)

    text, _markup = asyncio.run(check_panels.Check.ban_detail(2, "abc", None))
    assert text == _expected_db_fail("abc")
    assert text != _expected_not_found("abc")


class _Query:
    """Callback-query double that accepts exactly one answer."""

    data = "checkme_detail:abc"

    def __init__(self) -> None:
        self.answers: list[tuple[str | None, bool]] = []

    async def answer(
        self, text: str | None = None, *, show_alert: bool = False
    ) -> None:
        if self.answers:
            raise RuntimeError("callback query answered twice")
        self.answers.append((text, show_alert))


def test_a_failed_ban_read_shows_one_retry_alert(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The retry alert must be the single answer, not a swallowed second one."""

    async def _boom(ban_id: str) -> object:
        raise RuntimeError("db blip")

    monkeypatch.setattr(db.bans_db, "get_ban", _boom)
    query = _Query()

    result = asyncio.run(
        check._load_ban_for_callback(
            query,  # type: ignore[arg-type]
            "abc",
            "en-US",
            log_label="probe",
        )
    )

    assert result is None
    assert len(query.answers) == 1
    assert query.answers[0][1] is True


def test_ban_detail_genuine_miss_same_render(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _none(ban_id: str) -> None:
        return None

    monkeypatch.setattr(db.bans_db, "get_ban", _none)

    text, _markup = asyncio.run(check_panels.Check.ban_detail(2, "abc", None))
    assert text == _expected_not_found("abc")


def test_a_failed_counter_is_not_rendered_as_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A counter outage shows an explicit unknown, not a clean zero total."""

    async def _info(_bot: object, _uid: int) -> tuple[str, None]:
        return "Alice", None

    async def _meta(_uid: int) -> tuple[None, None, None]:
        return None, None, None

    async def _none(*_args: object) -> None:
        return None

    async def _three(_uid: int) -> int:
        return 3

    async def _boom(_uid: int) -> object:
        raise RuntimeError("db blip")

    async def _groups(_uid: int) -> list[tuple[int, int]]:
        return [(111, 2)]

    async def _zero(_uid: int) -> int:
        return 0

    monkeypatch.setattr(check_panels, "_resolve_user_info", _info)
    monkeypatch.setattr(db.users_roles, "role_meta", _meta)
    monkeypatch.setattr(db.bans_db, "get_active_ban", _none)
    monkeypatch.setattr(db.mutes_db, "get_active_mute", _none)
    monkeypatch.setattr(db.bans_db, "user_ban_count", _three)
    monkeypatch.setattr(db.bans_db, "user_appeal_count", _zero)
    monkeypatch.setattr(db.warns_db, "user_total_warns", _boom)
    monkeypatch.setattr(db.warns_db, "user_warn_groups", _groups)
    monkeypatch.setattr(db.kicks_db, "user_kick_count", _zero)
    monkeypatch.setattr(db.mutes_db, "user_mute_count", _zero)

    text, _markup = asyncio.run(
        check_panels.Check.profile(object(), 2, locale="en-US")  # type: ignore[arg-type]
    )

    assert t("checking.profile.unknown", "en-US") in text


def test_warns_by_group_titles_failure_renders_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _groups(user_id: int) -> list[tuple[int, int]]:
        return [(111, 3), (222, 1)]

    async def _boom(ids: list[int]) -> object:
        raise RuntimeError("db blip")

    monkeypatch.setattr(check_panels, "_name", _fake_name)
    monkeypatch.setattr(db.warns_db, "user_warn_groups", _groups)
    monkeypatch.setattr(db.groups_db, "get_group_titles", _boom)

    text, _markup = asyncio.run(check_panels.Check.warns_by_group(2, None))
    assert "111" in text
    assert "222" in text


def test_warns_by_group_normal_titles_unaffected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _groups(user_id: int) -> list[tuple[int, int]]:
        return [(111, 3)]

    async def _titles(ids: list[int]) -> dict[int, str]:
        return {111: "A Group"}

    monkeypatch.setattr(check_panels, "_name", _fake_name)
    monkeypatch.setattr(db.warns_db, "user_warn_groups", _groups)
    monkeypatch.setattr(db.groups_db, "get_group_titles", _titles)

    text, _markup = asyncio.run(check_panels.Check.warns_by_group(2, None))
    assert "A Group" in text


def test_warns_by_group_db_failure_renders_retry_card(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _boom(user_id: int) -> object:
        raise RuntimeError("db blip")

    monkeypatch.setattr(db.warns_db, "user_warn_groups", _boom)

    text, _markup = asyncio.run(check_panels.Check.warns_by_group(2, None))
    assert text == t("checking.warns.db_fail", None)
    assert text != t("checking.warns.empty", None, user=Safe(user_ref(2, "Alice")))
