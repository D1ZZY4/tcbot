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


# ─────────────────── cmd_tcfgroups handler tests ────────────────── #


import tcbot.modules.groups as groups_mod  # noqa: E402

# Bypass ratelimiter + log_execution decorators.
_cmd_tcfgroups = groups_mod.cmd_tcfgroups.__wrapped__.__wrapped__
_on_groups_details = groups_mod.on_groups_details.__wrapped__.__wrapped__
_on_groups_simple = groups_mod.on_groups_simple.__wrapped__.__wrapped__


def _make_update_for_groups(*, user_data: dict | None = None) -> object:
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock

    msg = AsyncMock()
    msg.reply_text = AsyncMock()

    update = MagicMock()
    update.effective_message = msg

    ctx = MagicMock()
    ctx.user_data = user_data if user_data is not None else {}

    return SimpleNamespace(update=update, ctx=ctx, msg=msg)


async def test_cmd_tcfgroups_no_groups_sends_empty_notice() -> None:
    """When no groups are connected, reply with a 'no groups' notice."""
    from unittest.mock import AsyncMock, patch

    env = _make_update_for_groups()
    with patch("tcbot.modules.groups.db") as mock_db:
        mock_db.groups_db.active_groups = AsyncMock(return_value=[])
        await _cmd_tcfgroups(env.update, env.ctx)

    env.msg.reply_text.assert_called_once()
    reply: str = env.msg.reply_text.call_args[0][0]
    assert "connected" in reply.lower() or "no group" in reply.lower()


async def test_cmd_tcfgroups_with_groups_sends_list() -> None:
    """When groups exist, reply must include the group title and HTML."""
    from unittest.mock import AsyncMock, patch

    grps = [{"title": "Alpha", "chat_id": -100001}]
    env = _make_update_for_groups()
    with patch("tcbot.modules.groups.db") as mock_db:
        mock_db.groups_db.active_groups = AsyncMock(return_value=grps)
        await _cmd_tcfgroups(env.update, env.ctx)

    env.msg.reply_text.assert_called_once()
    reply: str = env.msg.reply_text.call_args[0][0]
    assert "Alpha" in reply


async def test_cmd_tcfgroups_caches_groups_in_user_data() -> None:
    """Groups must be stored in ctx.user_data['groups_cache'] for toggle callbacks."""
    from unittest.mock import AsyncMock, patch

    grps = [{"title": "Beta", "chat_id": -100002}]
    env = _make_update_for_groups()
    with patch("tcbot.modules.groups.db") as mock_db:
        mock_db.groups_db.active_groups = AsyncMock(return_value=grps)
        await _cmd_tcfgroups(env.update, env.ctx)

    assert env.ctx.user_data.get("groups_cache") == grps


async def test_on_groups_details_uses_cache_and_skips_db() -> None:
    """on_groups_details with warm cache must skip the DB query."""
    from unittest.mock import AsyncMock, MagicMock, patch

    grps = [{"title": "Gamma", "chat_id": -100003}]
    q = AsyncMock()
    q.answer = AsyncMock()
    q.message = MagicMock()

    update = MagicMock()
    update.callback_query = q

    ctx = MagicMock()
    ctx.user_data = {"groups_cache": grps}

    with (
        patch("tcbot.modules.groups.db") as mock_db,
        patch("tcbot.modules.groups.safe_edit", new=AsyncMock()),
    ):
        mock_db.groups_db.active_groups = AsyncMock(return_value=[])
        await _on_groups_details(update, ctx)

    # DB must NOT have been called (cache hit)
    mock_db.groups_db.active_groups.assert_not_called()
    q.answer.assert_called_once()


async def test_on_groups_simple_fetches_db_on_cache_miss() -> None:
    """on_groups_simple without cache must fetch from DB exactly once."""
    from unittest.mock import AsyncMock, MagicMock, patch

    grps = [{"title": "Delta", "chat_id": -100004}]
    q = AsyncMock()
    q.answer = AsyncMock()
    q.message = MagicMock()

    update = MagicMock()
    update.callback_query = q

    ctx = MagicMock()
    ctx.user_data = {}

    with (
        patch("tcbot.modules.groups.db") as mock_db,
        patch("tcbot.modules.groups.safe_edit", new=AsyncMock()),
    ):
        mock_db.groups_db.active_groups = AsyncMock(return_value=grps)
        await _on_groups_simple(update, ctx)

    mock_db.groups_db.active_groups.assert_called_once()
    assert ctx.user_data.get("groups_cache") == grps
