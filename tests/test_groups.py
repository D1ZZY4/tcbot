# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""Tests for tcbot.modules.groups - _render (pure function)."""

from __future__ import annotations

from tcbot.modules.groups import _render

# ─────────────────────── header and count ──────────────────────── #


def test_render_always_includes_header() -> None:
    result = _render([], False)
    assert "Connected Groups" in result


def test_render_empty_list_shows_zero_count() -> None:
    result = _render([], False)
    assert "Count: 0" in result


def test_render_single_group_shows_count_one() -> None:
    groups = [{"title": "Alpha", "chat_id": -100001}]
    result = _render(groups, False)
    assert "Count: 1" in result


def test_render_multiple_groups_shows_correct_count() -> None:
    groups = [
        {"title": "Alpha", "chat_id": -100001},
        {"title": "Beta", "chat_id": -100002},
        {"title": "Gamma", "chat_id": -100003},
    ]
    result = _render(groups, False)
    assert "Count: 3" in result


# ────────────────────── simple view (not detailed) ─────────────── #


def test_render_simple_includes_group_title() -> None:
    groups = [{"title": "Test Group", "chat_id": -100123456}]
    result = _render(groups, False)
    assert "Test Group" in result


def test_render_simple_does_not_show_chat_id() -> None:
    """Simple view must not expose chat_id."""
    groups = [{"title": "Test Group", "chat_id": -100123456}]
    result = _render(groups, False)
    assert "-100123456" not in result
    assert "100123456" not in result


def test_render_simple_shows_all_titles() -> None:
    groups = [
        {"title": "Alpha Group", "chat_id": -100001},
        {"title": "Beta Group", "chat_id": -100002},
    ]
    result = _render(groups, False)
    assert "Alpha Group" in result
    assert "Beta Group" in result


# ─────────────────────── detailed view ─────────────────────────── #


def test_render_detailed_includes_group_title() -> None:
    groups = [{"title": "Test Group", "chat_id": -100123456}]
    result = _render(groups, True)
    assert "Test Group" in result


def test_render_detailed_includes_chat_id() -> None:
    groups = [{"title": "Test Group", "chat_id": -100123456}]
    result = _render(groups, True)
    assert "-100123456" in result


def test_render_detailed_shows_both_groups() -> None:
    groups = [
        {"title": "Alpha Group", "chat_id": -100001},
        {"title": "Beta Group", "chat_id": -100002},
    ]
    result = _render(groups, True)
    assert "Alpha Group" in result
    assert "-100001" in result
    assert "Beta Group" in result
    assert "-100002" in result


# ─────────────────────── html / escaping ───────────────────────── #


def test_render_returns_string() -> None:
    assert isinstance(_render([], False), str)
    assert isinstance(_render([], True), str)


def test_render_title_with_special_chars_does_not_crash() -> None:
    """Title containing HTML special chars must not raise."""
    groups = [{"title": "<Some & Group>", "chat_id": -100001}]
    result = _render(groups, False)
    assert "Some" in result or "&lt;" in result
