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
