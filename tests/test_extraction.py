# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""Tests for tcbot.modules.helper.extraction — ResolvedTarget and _best_name."""

from __future__ import annotations

from tcbot.modules.helper.extraction import ResolvedTarget, _best_name


class TestResolvedTarget:
    def test_stores_id_and_name(self):
        t = ResolvedTarget(id=42, first_name="Alice")
        assert t.id == 42
        assert t.first_name == "Alice"

    def test_username_defaults_to_none(self):
        t = ResolvedTarget(id=42, first_name="Alice")
        assert t.username is None

    def test_stores_username(self):
        t = ResolvedTarget(id=42, first_name="Alice", username="alice")
        assert t.username == "alice"

    def test_none_first_name_becomes_str_id(self):
        t = ResolvedTarget(id=42, first_name=None)
        assert t.first_name == "42"

    def test_empty_first_name_becomes_str_id(self):
        t = ResolvedTarget(id=99, first_name="")
        assert t.first_name == "99"

    def test_valid_first_name_kept(self):
        t = ResolvedTarget(id=1, first_name="Bob")
        assert t.first_name == "Bob"

    def test_raw_field_ignored_in_comparison(self):
        t1 = ResolvedTarget(id=1, first_name="A", raw=object())
        t2 = ResolvedTarget(id=1, first_name="A", raw=object())
        assert t1 == t2

    def test_raw_not_shown_in_repr(self):
        t = ResolvedTarget(id=1, first_name="A", raw=object())
        assert "raw" not in repr(t)


def _async_get_first_name(return_value: str):
    async def _impl(uid, default=""):
        return return_value

    return _impl


class TestBestName:
    async def test_returns_first_non_empty_primary(self, monkeypatch):
        monkeypatch.setattr(
            "tcbot.modules.helper.extraction.db.users_cache.get_first_name",
            _async_get_first_name(""),
        )
        result = await _best_name(42, "Alice", "Bob")
        assert result == "Alice"

    async def test_skips_none_primaries(self, monkeypatch):
        monkeypatch.setattr(
            "tcbot.modules.helper.extraction.db.users_cache.get_first_name",
            _async_get_first_name("Cached"),
        )
        result = await _best_name(42, None, None)
        assert result == "Cached"

    async def test_skips_empty_primaries(self, monkeypatch):
        monkeypatch.setattr(
            "tcbot.modules.helper.extraction.db.users_cache.get_first_name",
            _async_get_first_name("CachedName"),
        )
        result = await _best_name(42, "", "")
        assert result == "CachedName"

    async def test_falls_back_to_user_id_string(self, monkeypatch):
        monkeypatch.setattr(
            "tcbot.modules.helper.extraction.db.users_cache.get_first_name",
            _async_get_first_name(""),
        )
        result = await _best_name(42)
        assert result == "User 42"

    async def test_skips_digit_only_primaries(self, monkeypatch):
        monkeypatch.setattr(
            "tcbot.modules.helper.extraction.db.users_cache.get_first_name",
            _async_get_first_name("RealName"),
        )
        result = await _best_name(42, "123456", None)
        assert result == "RealName"

    async def test_accepts_numeric_id_as_fallback_label(self, monkeypatch):
        monkeypatch.setattr(
            "tcbot.modules.helper.extraction.db.users_cache.get_first_name",
            _async_get_first_name(""),
        )
        result = await _best_name(77777)
        assert result == "User 77777"

    async def test_cached_name_with_only_digits_also_skipped(self, monkeypatch):
        monkeypatch.setattr(
            "tcbot.modules.helper.extraction.db.users_cache.get_first_name",
            _async_get_first_name("99999"),
        )
        result = await _best_name(99)
        assert result == "User 99"
