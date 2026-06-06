# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Studio

"""Tests for tcbot.modules.helper.ban_info — build_ban_detail formatter."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from tcbot.modules.helper.ban_info import build_ban_detail


async def _fake_mention_data(uid: int) -> tuple[str, str | None]:
    names = {
        42: ("Alice", "alice"),
        99: ("Admin", "mod_admin"),
        0: ("Unknown", None),
    }
    return names.get(uid, (f"User {uid}", None))


def _ban(overrides: dict | None = None) -> dict:
    base = {
        "ban_id": "abc123xyz",
        "banned_user_id": 42,
        "admin_user_id": 99,
        "reason": "Spam and flood",
        "proof_message_id": 500,
        "timestamp": datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc),
        "is_active": True,
    }
    if overrides:
        base.update(overrides)
    return base


@pytest.fixture(autouse=True)
def patch_deps(monkeypatch):
    fake_cfg = MagicMock()
    fake_cfg.proofs = (-1001234567890, None)
    monkeypatch.setattr("tcbot.modules.helper.ban_info.cfg", fake_cfg)
    monkeypatch.setattr(
        "tcbot.modules.helper.ban_info.db.users_cache.get_user_mention_data",
        _fake_mention_data,
    )


class TestBuildBanDetail:
    async def test_returns_tuple(self):
        text, link = await build_ban_detail(_ban())
        assert isinstance(text, str)
        assert link is None or isinstance(link, str)

    async def test_contains_ban_id(self):
        text, _ = await build_ban_detail(_ban())
        assert "abc123xyz" in text

    async def test_contains_reason(self):
        text, _ = await build_ban_detail(_ban())
        assert "Spam and flood" in text

    async def test_contains_user_ids(self):
        text, _ = await build_ban_detail(_ban())
        assert "42" in text
        assert "99" in text

    async def test_proof_link_present_when_proof_message_id_set(self):
        _, link = await build_ban_detail(_ban({"proof_message_id": 500}))
        assert link is not None
        assert "500" in link

    async def test_no_proof_link_when_no_proof_message_id(self):
        _, link = await build_ban_detail(_ban({"proof_message_id": None}))
        assert link is None

    async def test_date_formatted_in_text(self):
        text, _ = await build_ban_detail(_ban())
        assert "2024" in text

    async def test_no_reason_fallback_text(self):
        ban = _ban({"reason": ""})
        text, _ = await build_ban_detail(ban)
        assert text

    async def test_missing_reason_field_uses_fallback(self):
        ban = {
            "ban_id": "xyz",
            "banned_user_id": 42,
            "admin_user_id": 99,
            "proof_message_id": None,
        }
        text, _ = await build_ban_detail(ban)
        from tcbot.modules.helper import replies as r

        assert r.NO_REASON in text

    async def test_skips_db_fetch_when_target_fname_provided(self, monkeypatch):
        call_count = 0

        async def counting_mention(uid):
            nonlocal call_count
            call_count += 1
            return (f"User {uid}", None)

        monkeypatch.setattr(
            "tcbot.modules.helper.ban_info.db.users_cache.get_user_mention_data",
            counting_mention,
        )
        await build_ban_detail(_ban(), target_fname="PreFetched")
        assert call_count == 1

    async def test_fetches_both_names_when_no_target_fname(self, monkeypatch):
        call_count = 0

        async def counting_mention(uid):
            nonlocal call_count
            call_count += 1
            return (f"User {uid}", None)

        monkeypatch.setattr(
            "tcbot.modules.helper.ban_info.db.users_cache.get_user_mention_data",
            counting_mention,
        )
        await build_ban_detail(_ban())
        assert call_count == 2

    async def test_escapes_html_in_reason(self):
        ban = _ban({"reason": "<script>xss</script>"})
        text, _ = await build_ban_detail(ban)
        assert "<script>" not in text

    async def test_no_timestamp_shows_unknown(self):
        ban = _ban({"timestamp": None})
        text, _ = await build_ban_detail(ban)
        assert "Unknown" in text

    async def test_ban_information_header_present(self):
        text, _ = await build_ban_detail(_ban())
        assert "Ban Information" in text
