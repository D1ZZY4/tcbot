# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Join-ban notices: the group message, the target DM, and their keyboard."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast

import pytest

from tcbot import database as db
from tcbot.database.types import BanId
from tcbot.modules import greeting
from tcbot.modules.helper.buttons import join_ban_btn

if TYPE_CHECKING:
    from telegram import Bot, Chat, Message, User

    from tcbot.database.documents import BanDoc


class _FakeBot:
    username: str | None = "tcbot"

    def __init__(self) -> None:
        self.sent: list[tuple[int, str, dict[str, Any]]] = []
        self.banned: list[tuple[int, int]] = []
        self.restricted: list[tuple[int, int]] = []

    async def ban_chat_member(self, chat_id: int, user_id: int) -> None:
        self.banned.append((chat_id, user_id))

    async def restrict_chat_member(
        self, chat_id: int, user_id: int, **kwargs: Any
    ) -> None:
        self.restricted.append((chat_id, user_id))

    async def send_message(self, chat_id: int, text: str, **kwargs: Any) -> object:
        self.sent.append((chat_id, text, kwargs))
        return object()


class _FakeMessage:
    def __init__(self) -> None:
        self.replies: list[tuple[str, dict[str, Any]]] = []

    async def reply_text(self, text: str, **kwargs: Any) -> object:
        self.replies.append((text, kwargs))
        return object()


class _FakeChat:
    id: int = -1001
    title: str = "Federation Chat"


class _FakeUser:
    id: int = 42
    first_name: str = "Alice"
    last_name: str = "Smith"
    username: str = "alice"
    is_bot: bool = False


def _ban_payload() -> BanDoc:
    return {
        "ban_id": BanId("BAN-0001"),
        "reason": "spam",
        "proof_message_id": 77,
        "log_message_id": 55,
    }


def _cfg() -> SimpleNamespace:
    return SimpleNamespace(
        proofs=(-100456, 7),
        logs=(-100123, 8),
        community_name="TCF",
    )


def test_join_ban_keyboard_puts_evidence_first_and_appeal_below() -> None:
    keyboard = join_ban_btn(
        "https://t.me/c/123/55?thread=8",
        "https://t.me/c/456/77?thread=7",
        "https://t.me/tcbot?start=appeal_BAN-0001",
        "en-US",
    )

    assert keyboard is not None
    rows = keyboard.inline_keyboard
    assert [button.text for button in rows[0]] == ["↝ View Log", "🖈 View Proof"]
    assert [button.text for button in rows[1]] == ["🗩 Submit Appeal"]


def test_join_ban_keyboard_drops_a_missing_link() -> None:
    keyboard = join_ban_btn(None, "https://t.me/c/456/77", None, "en-US")

    assert keyboard is not None
    assert [button.text for button in keyboard.inline_keyboard[0]] == ["🖈 View Proof"]


def test_the_group_notice_and_the_dm_are_different(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(greeting, "cfg", _cfg())
    bot = _FakeBot()
    message = _FakeMessage()

    asyncio.run(
        greeting._send_join_ban_notices(
            cast("Bot", bot),
            cast("Chat", _FakeChat()),
            cast("User", _FakeUser()),
            _ban_payload(),
            "en-US",
            reply_to=cast("Message", message),
        )
    )

    assert len(message.replies) == 1
    group_text, group_kwargs = message.replies[0]
    assert "<b>First name:</b> Alice" in group_text
    assert "<b>Username:</b> @alice" in group_text
    assert "<b>Ban ID:</b>" in group_text

    assert len(bot.sent) == 1
    dm_chat_id, dm_text, dm_kwargs = bot.sent[0]
    assert dm_chat_id == 42
    assert "banned from TCF" in dm_text
    assert "Federation Chat" in dm_text
    assert dm_text != group_text

    for kwargs in (group_kwargs, dm_kwargs):
        markup = kwargs["reply_markup"]
        labels = [[button.text for button in row] for row in markup.inline_keyboard]
        assert labels == [["↝ View Log", "🖈 View Proof"], ["🗩 Submit Appeal"]]


def test_the_dm_follows_the_banned_users_locale(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A member reading Indonesian must not get an English ban DM."""

    async def _id(_uid: int) -> str:
        return "id-ID"

    monkeypatch.setattr(greeting, "locale_for_user", _id)
    monkeypatch.setattr(greeting, "cfg", _cfg())
    bot = _FakeBot()

    asyncio.run(
        greeting._send_join_ban_notices(
            cast("Bot", bot),
            cast("Chat", _FakeChat()),
            cast("User", _FakeUser()),
            _ban_payload(),
            "en-US",
            reply_to=None,
        )
    )

    assert bot.sent
    dm_chat_id, dm_text, dm_kwargs = bot.sent[-1]
    assert dm_chat_id == 42
    assert "Kamu di-ban federasi" in dm_text
    assert "Ajukan Banding" in dm_text
    markup = dm_kwargs["reply_markup"]
    labels = [[button.text for button in row] for row in markup.inline_keyboard]
    assert any("Banding" in label for row in labels for label in row)


def test_connection_lookup_outage_still_enforces(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An is_connected outage must not skip ban enforcement on join."""

    async def _raise(*_args: object, **_kwargs: object) -> bool:
        raise RuntimeError("db down")

    monkeypatch.setattr(db.groups_db, "is_connected", _raise)
    monkeypatch.setattr(
        greeting,
        "cfg",
        SimpleNamespace(is_primary_group=lambda _cid: False),
    )

    async def run() -> object | None:
        return await greeting._in_federation(-1001, action="join_request")

    assert asyncio.run(run()) is None


def test_a_secondary_group_still_gets_the_ban_notice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The welcome is primary-only; the ban notice is not."""
    monkeypatch.setattr(greeting, "cfg", _cfg())

    async def _harvest(*args: object, **kwargs: object) -> None:
        return None

    async def _ban(*args: object, **kwargs: object) -> BanDoc:
        return _ban_payload()

    async def _mute(*args: object, **kwargs: object) -> None:
        return None

    async def _demote(*args: object, **kwargs: object) -> None:
        return None

    monkeypatch.setattr(db.users_cache, "harvest_user_identity", _harvest)
    monkeypatch.setattr(db.bans_db, "get_active_ban", _ban)
    monkeypatch.setattr(db.mutes_db, "get_active_mute", _mute)
    monkeypatch.setattr(greeting, "demote_before_enforcement", _demote)
    bot = _FakeBot()
    message = _FakeMessage()

    asyncio.run(
        greeting._handle_member(
            cast("User", _FakeUser()),
            cast("Message", message),
            cast("Chat", _FakeChat()),
            cast("Bot", bot),
            "en-US",
            greet=False,
        )
    )

    assert bot.banned == [(-1001, 42)]
    assert len(message.replies) == 1
    assert bot.sent and bot.sent[0][0] == 42


def test_join_enforcement_never_bans_the_protected_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A demote verdict of "owner" suppresses the Telegram ban on join."""

    async def _harvest(*args: object, **kwargs: object) -> None:
        return None

    async def _ban(*args: object, **kwargs: object) -> BanDoc:
        return _ban_payload()

    async def _mute(*args: object, **kwargs: object) -> None:
        return None

    async def _demote(*args: object, **kwargs: object) -> str:
        return "owner"

    monkeypatch.setattr(db.users_cache, "harvest_user_identity", _harvest)
    monkeypatch.setattr(db.bans_db, "get_active_ban", _ban)
    monkeypatch.setattr(db.mutes_db, "get_active_mute", _mute)
    monkeypatch.setattr(greeting, "demote_before_enforcement", _demote)
    bot = _FakeBot()

    asyncio.run(
        greeting._handle_member(
            cast("User", _FakeUser()),
            cast("Message", _FakeMessage()),
            cast("Chat", _FakeChat()),
            cast("Bot", bot),
            "en-US",
        )
    )

    assert bot.banned == []


def test_join_enforcement_never_mutes_the_protected_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A demote verdict of "owner" suppresses the Telegram mute on join."""

    async def _harvest(*args: object, **kwargs: object) -> None:
        return None

    async def _ban(*args: object, **kwargs: object) -> None:
        return None

    async def _mute(*args: object, **kwargs: object) -> dict[str, object]:
        return {"until_date": None}

    async def _demote(*args: object, **kwargs: object) -> str:
        return "owner"

    monkeypatch.setattr(db.users_cache, "harvest_user_identity", _harvest)
    monkeypatch.setattr(db.bans_db, "get_active_ban", _ban)
    monkeypatch.setattr(db.mutes_db, "get_active_mute", _mute)
    monkeypatch.setattr(greeting, "demote_before_enforcement", _demote)
    bot = _FakeBot()

    asyncio.run(
        greeting._handle_member(
            cast("User", _FakeUser()),
            cast("Message", _FakeMessage()),
            cast("Chat", _FakeChat()),
            cast("Bot", bot),
            "en-US",
            greet=False,
        )
    )

    assert bot.restricted == []
