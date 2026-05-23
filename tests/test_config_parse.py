# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""
Tests for config parsing helpers in tcbot.__init__.
"""

from __future__ import annotations

from tcbot import parse_list


def test_parse_list_accepts_python_list_literal() -> None:
    assert parse_list('["/", "!", "."]') == ["/", "!", "."]


def test_parse_list_falls_back_to_csv_strings() -> None:
    assert parse_list("/,!,.") == ["/", "!", "."]
