# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""Tests for :mod:`tcbot.modules.helper.extraction` – target resolution helpers."""
from __future__ import annotations

from types import SimpleNamespace

from tcbot.modules.helper.extraction import ResolvedTarget, get_reason


def test_resolved_target_falls_back_to_string_id_when_no_first_name() -> None:
    rt = ResolvedTarget(42, None, None)
    assert rt.id == 42
    assert rt.first_name == "42"
    assert rt.username is None


def test_resolved_target_keeps_provided_fields() -> None:
    raw = SimpleNamespace(label="user-object")
    rt = ResolvedTarget(7, "Andi", "andi", raw=raw)
    assert rt.id == 7
    assert rt.first_name == "Andi"
    assert rt.username == "andi"
    assert rt.raw is raw


def test_get_reason_uses_full_args_for_reply() -> None:
    update = SimpleNamespace(
        effective_message=SimpleNamespace(
            reply_to_message=SimpleNamespace(from_user=SimpleNamespace(id=1)),
        )
    )
    context = SimpleNamespace(args=["spam", "abuse"])
    assert get_reason(context, update) == "spam abuse"


def test_get_reason_skips_first_arg_for_target_form() -> None:
    update = SimpleNamespace(effective_message=SimpleNamespace(reply_to_message=None))
    context = SimpleNamespace(args=["@user", "spam", "abuse"])
    assert get_reason(context, update) == "spam abuse"


def test_get_reason_returns_empty_when_no_args() -> None:
    update = SimpleNamespace(effective_message=SimpleNamespace(reply_to_message=None))
    context = SimpleNamespace(args=[])
    assert get_reason(context, update) == ""


def test_get_reason_handles_missing_message() -> None:
    update = SimpleNamespace(effective_message=None)
    context = SimpleNamespace(args=["x", "y"])
    assert get_reason(context, update) == "y"
