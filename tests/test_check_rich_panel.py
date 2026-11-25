# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""The /check profile and warning summary are real rich blocks, not flat text."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from tcbot.modules.helper.pipelines import check_panels
from tcbot.utils.i18n import t


@pytest.fixture
def _stub_profile_reads(monkeypatch: pytest.MonkeyPatch) -> None:
    """Return deterministic, healthy data for every profile read."""

    async def _user_info(bot: Any, target_id: int) -> tuple[str, str | None]:
        return "Alice", "alice"

    async def _role_meta(user_id: int) -> tuple[str | None, int | None, Any]:
        return "moderator", 7, None

    async def _none(*args: Any, **kwargs: Any) -> None:
        return None

    async def _zero(*args: Any, **kwargs: Any) -> int:
        return 0

    async def _no_groups(*args: Any, **kwargs: Any) -> list[Any]:
        return []

    async def _first_name(user_id: int, fallback: str) -> str:
        return fallback

    monkeypatch.setattr(check_panels.db.users_cache, "get_first_name", _first_name)
    monkeypatch.setattr(check_panels, "_resolve_user_info", _user_info)
    monkeypatch.setattr(check_panels.db.users_roles, "role_meta", _role_meta)
    monkeypatch.setattr(check_panels.db.bans_db, "get_active_ban", _none)
    monkeypatch.setattr(check_panels.db.mutes_db, "get_active_mute", _none)
    monkeypatch.setattr(check_panels.db.bans_db, "user_ban_count", _zero)
    monkeypatch.setattr(check_panels.db.bans_db, "user_appeal_count", _zero)
    monkeypatch.setattr(check_panels.db.warns_db, "user_total_warns", _zero)
    monkeypatch.setattr(check_panels.db.warns_db, "user_warn_groups", _no_groups)
    monkeypatch.setattr(check_panels.db.kicks_db, "user_kick_count", _zero)
    monkeypatch.setattr(check_panels.db.mutes_db, "user_mute_count", _zero)


@pytest.mark.parametrize("locale", ("en-US", "id-ID"))
def test_profile_is_heading_divider_and_two_tables(
    monkeypatch: pytest.MonkeyPatch, _stub_profile_reads: None, locale: str
) -> None:
    """A reader sees two titled sections, each a divider and a table."""
    text, _markup = asyncio.run(
        check_panels.Check.profile(object(), 42, locale=locale)  # type: ignore[arg-type]
    )

    assert text.startswith("<h2>")
    assert t("checking.profile.title", locale, plain=True) in text
    assert t("checking.profile.activity", locale, plain=True) in text
    assert text.count("<hr/>") == 2
    assert text.count("<table") == 2
    assert t("checking.profile.table.field", locale, plain=True) in text
    assert t("checking.profile.table.value", locale, plain=True) in text
    # * The identity and counters are cells, not a flat list of paragraphs.
    assert "<p>" not in text
    assert "<code>42</code>" in text
    assert "Alice" in text


@pytest.mark.parametrize("locale", ("en-US", "id-ID"))
def test_profile_username_is_escaped_once(
    monkeypatch: pytest.MonkeyPatch, _stub_profile_reads: None, locale: str
) -> None:
    """The catalog renderer escapes placeholders; callers must not pre-escape."""

    async def _user_info(bot: Any, target_id: int) -> tuple[str, str | None]:
        return "Alice", "a&b<c>"

    monkeypatch.setattr(check_panels, "_resolve_user_info", _user_info)
    text, _markup = asyncio.run(
        check_panels.Check.profile(object(), 42, locale=locale)  # type: ignore[arg-type]
    )

    assert "@a&amp;b&lt;c&gt;" in text
    assert "&amp;amp;" not in text
    assert "&amp;lt;" not in text


@pytest.mark.parametrize("locale", ("en-US", "id-ID"))
def test_warning_summary_uses_a_table(
    monkeypatch: pytest.MonkeyPatch, locale: str
) -> None:
    """The per-group warning view is a table with group and count columns."""

    async def _groups(user_id: int) -> list[tuple[int, int]]:
        return [(111, 3), (222, 1)]

    async def _name(user_id: int) -> str:
        return "Alice"

    async def _titles(ids: list[int]) -> dict[int, str]:
        return {111: "A Group", 222: "B Group"}

    monkeypatch.setattr(check_panels, "_name", _name)
    monkeypatch.setattr(check_panels.db.warns_db, "user_warn_groups", _groups)
    monkeypatch.setattr(check_panels.db.groups_db, "get_group_titles", _titles)

    text, _markup = asyncio.run(check_panels.Check.warns_by_group(42, locale))

    assert text.startswith("<h2>")
    assert t("checking.warns.table.group", locale, plain=True) in text
    assert t("checking.warns.table.count", locale, plain=True) in text
    assert "<hr/>" in text
    assert text.count("<table") == 1
    assert "A Group" in text
    assert "B Group" in text
    assert "<p>" not in text
    assert "<li>" not in text


def test_recognition_note_needs_no_fresh_role_read(
    monkeypatch: pytest.MonkeyPatch, _stub_profile_reads: None
) -> None:
    """The profile note only names special identities, not federation roles."""
    reads: list[int] = []

    async def _unexpected_role(*args: Any, **kwargs: Any) -> str:
        _ = (args, kwargs)
        reads.append(1)
        raise AssertionError("the profile note must not resolve a role")

    monkeypatch.setattr(
        check_panels.db.users_roles, "get_effective_role", _unexpected_role
    )

    text, _markup = asyncio.run(
        check_panels.Check.profile(
            object(),
            42,
            executor_id=42,
            locale="en-US",  # type: ignore[arg-type]
        )
    )

    assert reads == []
    assert t("identity.note.self", "en-US") in text
