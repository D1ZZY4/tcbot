# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""
Tests for tcbot.modules.helper.extraction — ResolvedTarget and get_reason.
"""

from __future__ import annotations

from types import SimpleNamespace

from tcbot.modules.helper.extraction import ResolvedTarget, get_reason


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


def test_get_reason_uses_full_args_for_reply_command() -> None:
    update = SimpleNamespace(
        effective_message=SimpleNamespace(
            reply_to_message=SimpleNamespace(from_user=SimpleNamespace(id=1))
        )
    )
    context = SimpleNamespace(args=["spam", "links"])
    assert get_reason(context, update) == "spam links"


def test_get_reason_skips_first_arg_for_target_form() -> None:
    update = SimpleNamespace(effective_message=SimpleNamespace(reply_to_message=None))
    context = SimpleNamespace(args=["@user", "spam", "links"])
    assert get_reason(context, update) == "spam links"


def test_get_reason_returns_empty_when_no_args() -> None:
    update = SimpleNamespace(effective_message=SimpleNamespace(reply_to_message=None))
    context = SimpleNamespace(args=[])
    assert get_reason(context, update) == ""


def test_get_reason_handles_missing_message() -> None:
    update = SimpleNamespace(effective_message=None)
    context = SimpleNamespace(args=["target", "reason"])
    assert get_reason(context, update) == "reason"


def test_get_reason_handles_reply_to_without_from_user() -> None:
    update = SimpleNamespace(
        effective_message=SimpleNamespace(
            reply_to_message=SimpleNamespace(from_user=None)
        )
    )
    context = SimpleNamespace(args=["@user", "reason"])
    assert get_reason(context, update) == "reason"
