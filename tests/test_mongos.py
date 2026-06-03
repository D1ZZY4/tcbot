# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""Tests for tcbot.database.mongos — offline-safe pure-function coverage."""

from __future__ import annotations

import pytest

import tcbot.database.mongos as mongos


class TestMakeShortId:
    def test_returns_string(self):
        result = mongos.make_short_id()
        assert isinstance(result, str)

    def test_default_length_is_ten(self):
        result = mongos.make_short_id()
        assert len(result) == 10

    def test_custom_length(self):
        result = mongos.make_short_id(20)
        assert len(result) == 20

    def test_only_lowercase_alnum(self):
        for _ in range(20):
            result = mongos.make_short_id()
            assert result.islower() or result.isdigit() or result.isalnum()
            assert result == result.lower()
            assert all(c.isalnum() for c in result)

    def test_unique_across_calls(self):
        ids = {mongos.make_short_id() for _ in range(100)}
        assert len(ids) == 100

    def test_length_one(self):
        result = mongos.make_short_id(1)
        assert len(result) == 1

    def test_length_zero_returns_empty(self):
        result = mongos.make_short_id(0)
        assert result == ""


class TestDb:
    def test_raises_when_not_initialised(self, monkeypatch):
        monkeypatch.setattr(mongos, "_db", None)
        with pytest.raises(RuntimeError, match="not initialised"):
            mongos.db()

    def test_returns_db_when_set(self, monkeypatch):
        fake_db = object()
        monkeypatch.setattr(mongos, "_db", fake_db)
        assert mongos.db() is fake_db


class TestMakeShortIdExtra:
    def test_no_uppercase_in_result(self):
        for _ in range(30):
            result = mongos.make_short_id()
            assert result == result.lower(), f"Uppercase found: {result!r}"

    def test_no_special_chars(self):
        for _ in range(30):
            result = mongos.make_short_id()
            assert result.isalnum(), f"Non-alnum character found: {result!r}"

    def test_large_length(self):
        result = mongos.make_short_id(50)
        assert len(result) == 50
        assert result.isalnum()

    def test_results_differ_between_calls(self):
        """Two consecutive short IDs should (almost certainly) differ."""
        a = mongos.make_short_id()
        b = mongos.make_short_id()
        assert a != b
