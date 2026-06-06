# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Studio

"""Tests for tcbot.modules.greeting - _handle_member ban-on-join logic."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from tcbot.modules.greeting import _handle_member

# ───────────────────────── Helpers ──────────────────────────────── #


def _make_member(
    *,
    is_bot: bool = False,
    uid: int = 42,
    username: str = "alice",
    first_name: str = "Alice",
) -> MagicMock:
    m = MagicMock()
    m.is_bot = is_bot
    m.id = uid
    m.username = username
    m.first_name = first_name
    m.last_name = None
    return m


def _make_chat(*, chat_id: int = -1001234567890) -> MagicMock:
    c = MagicMock()
    c.id = chat_id
    return c


# ──────────────────── bot member → early return ─────────────────── #


async def test_handle_member_bot_skipped() -> None:
    """Bot accounts must be silently skipped - no DB calls, no messages."""
    member = _make_member(is_bot=True, uid=100)
    msg = AsyncMock()
    chat = _make_chat()
    bot = AsyncMock()

    with patch("tcbot.modules.greeting.db"):
        await _handle_member(member, msg, chat, bot)

    msg.reply_text.assert_not_called()
    bot.ban_chat_member.assert_not_called()


# ─────────────────── unbanned user → welcome ────────────────────── #


async def test_handle_member_unbanned_gets_welcome_message() -> None:
    member = _make_member(uid=42, first_name="Alice", username="alice")
    msg = AsyncMock()
    chat = _make_chat()
    bot = AsyncMock()

    with patch("tcbot.modules.greeting.db") as mock_db:
        mock_db.users_cache.upsert_user = AsyncMock(return_value=None)
        mock_db.bans_db.get_active_ban = AsyncMock(return_value=None)
        await _handle_member(member, msg, chat, bot)

    msg.reply_text.assert_called_once()
    welcome_text: str = msg.reply_text.call_args[0][0]
    assert "Alice" in welcome_text


async def test_handle_member_unbanned_does_not_ban() -> None:
    member = _make_member(uid=42)
    msg = AsyncMock()
    chat = _make_chat()
    bot = AsyncMock()

    with patch("tcbot.modules.greeting.db") as mock_db:
        mock_db.users_cache.upsert_user = AsyncMock(return_value=None)
        mock_db.bans_db.get_active_ban = AsyncMock(return_value=None)
        await _handle_member(member, msg, chat, bot)

    bot.ban_chat_member.assert_not_called()


# ─────────────────── banned user → auto-remove ──────────────────── #


async def test_handle_member_banned_user_triggers_ban() -> None:
    member = _make_member(uid=99, first_name="Banned", username="banned")
    msg = AsyncMock()
    chat = _make_chat(chat_id=-1001000000001)
    bot = AsyncMock()
    ban_record = {"user_id": 99, "reason": "spam"}

    with patch("tcbot.modules.greeting.db") as mock_db:
        mock_db.users_cache.upsert_user = AsyncMock(return_value=None)
        mock_db.bans_db.get_active_ban = AsyncMock(return_value=ban_record)
        await _handle_member(member, msg, chat, bot)

    bot.ban_chat_member.assert_called_once_with(chat.id, member.id)


async def test_handle_member_banned_user_sends_notification() -> None:
    """A public notice should be sent when a federation-banned user is removed."""
    member = _make_member(uid=99, first_name="Banned", username="banned")
    msg = AsyncMock()
    chat = _make_chat()
    bot = AsyncMock()
    ban_record = {"user_id": 99, "reason": "spam"}

    with patch("tcbot.modules.greeting.db") as mock_db:
        mock_db.users_cache.upsert_user = AsyncMock(return_value=None)
        mock_db.bans_db.get_active_ban = AsyncMock(return_value=ban_record)
        await _handle_member(member, msg, chat, bot)

    msg.reply_text.assert_called_once()
    notice: str = msg.reply_text.call_args[0][0]
    assert "Banned" in notice or "banned" in notice.lower()


async def test_handle_member_banned_no_welcome_sent() -> None:
    """Banned members must not receive a welcome message."""
    member = _make_member(uid=99)
    msg = AsyncMock()
    chat = _make_chat()
    bot = AsyncMock()
    ban_record = {"user_id": 99, "reason": "spam"}

    with patch("tcbot.modules.greeting.db") as mock_db:
        mock_db.users_cache.upsert_user = AsyncMock(return_value=None)
        mock_db.bans_db.get_active_ban = AsyncMock(return_value=ban_record)
        await _handle_member(member, msg, chat, bot)

    # The single call must be the removal notice, not a "Welcome" message
    call_text: str = msg.reply_text.call_args[0][0]
    assert "Welcome" not in call_text


# ───────────────── upsert_user always called ────────────────────── #


async def test_handle_member_always_upserts_cache() -> None:
    """Cache upsert must run regardless of ban status."""
    member = _make_member(uid=42, first_name="Alice", username="alice")
    msg = AsyncMock()
    chat = _make_chat()
    bot = AsyncMock()

    with patch("tcbot.modules.greeting.db") as mock_db:
        mock_db.users_cache.upsert_user = AsyncMock(return_value=None)
        mock_db.bans_db.get_active_ban = AsyncMock(return_value=None)
        await _handle_member(member, msg, chat, bot)

    mock_db.users_cache.upsert_user.assert_called_once_with(
        member.id, member.username, member.first_name, member.last_name
    )


# ───────────────── ban failure is silently logged ───────────────── #


async def test_handle_member_ban_exception_does_not_propagate() -> None:
    """A ban error (e.g. bot lacks permissions) must be caught; no exception raised."""
    member = _make_member(uid=99, first_name="Banned", username="banned")
    msg = AsyncMock()
    chat = _make_chat()
    bot = AsyncMock()
    bot.ban_chat_member.side_effect = Exception("No permission")
    ban_record = {"user_id": 99, "reason": "spam"}

    with patch("tcbot.modules.greeting.db") as mock_db:
        mock_db.users_cache.upsert_user = AsyncMock(return_value=None)
        mock_db.bans_db.get_active_ban = AsyncMock(return_value=ban_record)
        # Must not raise
        await _handle_member(member, msg, chat, bot)


# ──────────────────── on_new_member handler ──────────────────────── #


from tcbot.modules.greeting import on_left_member, on_new_member  # noqa: E402


def _make_new_member_update(*, chat_id: int, new_members: list) -> object:
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock

    msg = AsyncMock()
    msg.new_chat_members = new_members
    msg.reply_text = AsyncMock()

    chat = MagicMock()
    chat.id = chat_id

    update = MagicMock()
    update.effective_message = msg
    update.effective_chat = chat

    ctx = MagicMock()
    ctx.bot = AsyncMock()

    return SimpleNamespace(update=update, ctx=ctx, msg=msg)


async def test_on_new_member_ignores_unrelated_chat() -> None:
    """Handler must do nothing when chat is not main_group or exec_group."""
    from unittest.mock import patch

    member = _make_member(uid=50)
    env = _make_new_member_update(chat_id=-999999, new_members=[member])

    with (
        patch("tcbot.modules.greeting.cfg") as mock_cfg,
        patch("tcbot.modules.greeting.db"),
    ):
        mock_cfg.main_group = -1001
        mock_cfg.exec_group = -1002
        await on_new_member(env.update, env.ctx)

    env.msg.reply_text.assert_not_called()


async def test_on_new_member_processes_member_in_main_group() -> None:
    """Handler must greet a new unbanned member in the configured main_group."""
    from unittest.mock import AsyncMock, patch

    member = _make_member(uid=77, first_name="Dave", username="dave")
    env = _make_new_member_update(chat_id=-1001, new_members=[member])

    with (
        patch("tcbot.modules.greeting.cfg") as mock_cfg,
        patch("tcbot.modules.greeting.db") as mock_db,
    ):
        mock_cfg.main_group = -1001
        mock_cfg.exec_group = -1002
        mock_cfg.community_name = "TCF"
        mock_db.users_cache.upsert_user = AsyncMock(return_value=None)
        mock_db.bans_db.get_active_ban = AsyncMock(return_value=None)
        await on_new_member(env.update, env.ctx)

    env.msg.reply_text.assert_called_once()
    welcome: str = env.msg.reply_text.call_args[0][0]
    assert "Dave" in welcome


# ──────────────────── on_left_member handler ─────────────────────── #


def _make_left_member_update(*, chat_id: int, left_member) -> object:
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock

    msg = AsyncMock()
    msg.left_chat_member = left_member
    msg.reply_text = AsyncMock()

    chat = MagicMock()
    chat.id = chat_id

    update = MagicMock()
    update.effective_message = msg
    update.effective_chat = chat

    ctx = MagicMock()

    return SimpleNamespace(update=update, ctx=ctx, msg=msg)


async def test_on_left_member_ignores_unrelated_chat() -> None:
    """Handler must do nothing when chat is not main_group or exec_group."""
    from unittest.mock import patch

    member = _make_member(uid=50)
    env = _make_left_member_update(chat_id=-999999, left_member=member)

    with patch("tcbot.modules.greeting.cfg") as mock_cfg:
        mock_cfg.main_group = -1001
        mock_cfg.exec_group = -1002
        await on_left_member(env.update, env.ctx)

    env.msg.reply_text.assert_not_called()


async def test_on_left_member_announces_departure() -> None:
    """Handler must send a departure notice for a non-bot member in main_group."""
    from unittest.mock import patch

    member = _make_member(uid=88, first_name="Eve", username="eve")
    env = _make_left_member_update(chat_id=-1001, left_member=member)

    with patch("tcbot.modules.greeting.cfg") as mock_cfg:
        mock_cfg.main_group = -1001
        mock_cfg.exec_group = -1002
        await on_left_member(env.update, env.ctx)

    env.msg.reply_text.assert_called_once()
    notice: str = env.msg.reply_text.call_args[0][0]
    assert "Eve" in notice or "left" in notice.lower()


async def test_on_left_member_skips_bot_departure() -> None:
    """Bot departures must not trigger a farewell notice."""
    from unittest.mock import patch

    member = _make_member(uid=200, is_bot=True)
    env = _make_left_member_update(chat_id=-1001, left_member=member)

    with patch("tcbot.modules.greeting.cfg") as mock_cfg:
        mock_cfg.main_group = -1001
        mock_cfg.exec_group = -1002
        await on_left_member(env.update, env.ctx)

    env.msg.reply_text.assert_not_called()


async def test_on_left_member_skips_none_member() -> None:
    """None left_chat_member must be silently skipped."""
    from unittest.mock import patch

    env = _make_left_member_update(chat_id=-1001, left_member=None)

    with patch("tcbot.modules.greeting.cfg") as mock_cfg:
        mock_cfg.main_group = -1001
        mock_cfg.exec_group = -1002
        await on_left_member(env.update, env.ctx)

    env.msg.reply_text.assert_not_called()
