# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""Tests for tcbot.modules.helper.extraction - ResolvedTarget."""

from __future__ import annotations

from types import SimpleNamespace

from tcbot.modules.helper.extraction import ResolvedTarget


def test_resolved_target_sets_first_name_to_str_id_when_none() -> None:
    rt = ResolvedTarget(id=42, first_name=None, username=None)
    assert rt.first_name == "42"


def test_resolved_target_keeps_provided_first_name() -> None:
    rt = ResolvedTarget(id=7, first_name="Andi", username="andi")
    assert rt.first_name == "Andi"
    assert rt.username == "andi"


def test_resolved_target_raw_field_stored() -> None:
    raw = SimpleNamespace(label="user")
    rt = ResolvedTarget(id=7, first_name="Andi", raw=raw)
    assert rt.raw is raw


def test_resolved_target_default_raw_is_none() -> None:
    rt = ResolvedTarget(id=1, first_name="Bob")
    assert rt.raw is None


def test_resolved_target_zero_id_sets_first_name_to_zero_string() -> None:
    rt = ResolvedTarget(id=0, first_name=None)
    assert rt.first_name == "0"


def test_resolved_target_large_id_preserved() -> None:
    rt = ResolvedTarget(id=9999999999, first_name=None)
    assert rt.id == 9999999999
    assert rt.first_name == "9999999999"


def test_resolved_target_negative_id_preserved() -> None:
    rt = ResolvedTarget(id=-100001234, first_name="Group")
    assert rt.id == -100001234
    assert rt.first_name == "Group"


def test_resolved_target_username_none_by_default() -> None:
    rt = ResolvedTarget(id=5, first_name="Alice")
    assert rt.username is None


def test_resolved_target_empty_string_replaced_with_id() -> None:
    """Empty string is falsy, so __post_init__ replaces it with str(id)."""
    rt = ResolvedTarget(id=5, first_name="")
    assert rt.first_name == "5"
