# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Identity refusal copy, staff notices, and recognition notes."""

from __future__ import annotations

from tcbot.modules.helper.identity import (
    Identity,
    profile_note,
    refuse_message,
    staff_notice,
)


def _ident(kind: str) -> Identity:
    """Build a fixed identity for copy assertions."""
    return Identity(kind, 123, "Dizzy", "dizzy")  # type: ignore[arg-type]


def test_ban_refuses_self_bot_telegram_anon_founder() -> None:
    for kind in ("self", "this_bot", "telegram", "anon_admin", "founder"):
        assert isinstance(refuse_message("ban", _ident(kind)), str)


def test_ban_allows_user_and_staff() -> None:
    for kind in ("user", "admin", "developer", "tester", "other_bot"):
        assert refuse_message("ban", _ident(kind)) is None


def test_unknown_action_allows_everything() -> None:
    assert refuse_message("nope", _ident("self")) is None
    assert refuse_message("nope", _ident("user")) is None


def test_promote_refuses_admin() -> None:
    assert isinstance(refuse_message("promote", _ident("admin")), str)


def test_staff_notice_only_for_staff() -> None:
    for kind in ("admin", "developer", "tester"):
        notice = staff_notice("warn", _ident(kind), "TCF")
        assert notice is not None and "warn" in notice
    for kind in ("user", "founder", "self", "other_bot"):
        assert staff_notice("warn", _ident(kind), "TCF") is None


def test_profile_note_only_for_special_identities() -> None:
    for kind in ("this_bot", "self", "telegram", "anon_admin"):
        assert isinstance(profile_note(_ident(kind)), str)
    for kind in ("user", "admin", "developer", "tester", "founder", "other_bot"):
        assert profile_note(_ident(kind)) is None


def test_role_label_maps_staff_only() -> None:
    assert _ident("admin").role_label == "Admin"
    assert _ident("founder").role_label == "Founder"
    assert _ident("user").role_label is None
    assert _ident("self").role_label is None
