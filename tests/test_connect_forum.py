# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Forum connect prompt behaviour when the bot is added anonymously."""

from __future__ import annotations

import asyncio
import inspect
from types import SimpleNamespace
from types import SimpleNamespace as _NS

import pytest
from pyrogram import ContinuePropagation
from pyrogram.enums import ChatMemberStatus

from tcbot.modules import connect as connect_module
from tcbot.modules.helper.pipelines import connect_added


class _FakeBot:
    """Record outbound messages without touching Telegram."""

    def __init__(self) -> None:
        self.sent: list[tuple[int, object]] = []

    async def send_message(
        self,
        chat_id: int,
        text: str,
        reply_markup: object | None = None,
        message_thread_id: int | None = None,
    ) -> SimpleNamespace:
        self.sent.append((chat_id, reply_markup))
        return SimpleNamespace(id=77, message_id=77)


class _FakeMessage:
    """Capture the reply of a command that refuses before doing any work."""

    def __init__(self, chat_type: str) -> None:
        self.chat = SimpleNamespace(id=-1001234567890, type=chat_type, title="Chat")
        self.text = "/tcconnect"
        self.replies: list[str] = []

    async def reply_text(self, text: str, parse_mode: str | None = None) -> None:
        self.replies.append(text)


def _forum_update(adder: object | None) -> SimpleNamespace:
    """Build the MY_CHAT_MEMBER update for a forum supergroup."""
    chat = SimpleNamespace(
        id=-1001234567890,
        type="supergroup",
        title="Community Forum",
        is_forum=True,
    )
    cmc = SimpleNamespace(
        chat=chat,
        new_chat_member=SimpleNamespace(status=ChatMemberStatus.MEMBER),
        old_chat_member=SimpleNamespace(status=ChatMemberStatus.LEFT),
        from_user=adder,
    )
    return SimpleNamespace(my_chat_member=cmc)


@pytest.mark.asyncio
async def test_forum_prompt_is_sent_without_an_attributed_adder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An anonymous forum admin must not suppress the owner's prompt."""
    bot = _FakeBot()
    ctx = SimpleNamespace(bot=bot)
    recorded: list[tuple[int, str, int, int]] = []

    async def _get_pending(_chat_id: int) -> None:
        return None

    async def _is_connected(_chat_id: int, *, fresh: bool = False) -> bool:
        return False

    async def _add_pending(
        chat_id: int, title: str, owner_id: int, message_id: int
    ) -> None:
        recorded.append((chat_id, title, owner_id, message_id))

    async def _locale(_update: object) -> str:
        return "en-US"

    monkeypatch.setattr(
        connect_added,
        "cfg",
        SimpleNamespace(
            is_primary_group=lambda _chat_id: False,
            is_infrastructure_chat=lambda _chat_id: False,
        ),
    )
    monkeypatch.setattr(connect_added, "locale_for_update", _locale)
    monkeypatch.setattr(connect_added.db.groups_db, "get_pending", _get_pending)
    monkeypatch.setattr(connect_added.db.groups_db, "is_connected", _is_connected)
    monkeypatch.setattr(connect_added.db.groups_db, "add_pending", _add_pending)

    await connect_added.connection.on_bot_added(
        _forum_update(None),  # type: ignore[arg-type]
        ctx,  # type: ignore[arg-type]
    )

    assert len(bot.sent) == 1
    assert recorded == [(-1001234567890, "Community Forum", 0, 77)]


@pytest.mark.asyncio
async def test_bot_added_to_infrastructure_group_sends_no_connect_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A deployment destination must never be asked to join the federation."""
    bot = _FakeBot()

    async def _must_not_be_called(*args: object, **kwargs: object) -> object:
        raise AssertionError("connection state must not be read for infrastructure")

    async def _locale(_update: object) -> str:
        return "en-US"

    monkeypatch.setattr(
        connect_added,
        "cfg",
        _NS(
            is_primary_group=lambda _chat_id: False,
            is_infrastructure_chat=lambda _chat_id: True,
        ),
    )
    monkeypatch.setattr(connect_added, "locale_for_update", _locale)
    monkeypatch.setattr(connect_added.db.groups_db, "get_pending", _must_not_be_called)
    monkeypatch.setattr(connect_added.db.groups_db, "is_connected", _must_not_be_called)
    monkeypatch.setattr(connect_added.db.groups_db, "add_pending", _must_not_be_called)

    await connect_added.connection.on_bot_added(
        _forum_update(SimpleNamespace(id=4242)),  # type: ignore[arg-type]
        _NS(bot=bot),  # type: ignore[arg-type]
    )

    assert bot.sent == []


@pytest.mark.asyncio
async def test_a_human_member_update_is_passed_to_the_next_handler() -> None:
    """The bot-added handler must not consume join-request approval updates."""
    update = _forum_update(None)
    update.my_chat_member.new_chat_member.user = SimpleNamespace(id=4242)

    async def _identity() -> SimpleNamespace:
        return SimpleNamespace(id=777000)

    ctx = _NS(
        bot=_FakeBot(),
        bot_identity=_identity,
        chat_member=update.my_chat_member,
    )
    with pytest.raises(ContinuePropagation):
        await connect_added.connection.on_bot_added(ctx)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_join_prompt_uses_the_rich_transport_with_buttons(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Connect/Cancel prompt goes through send_text so buttons render rich."""
    sent: list[dict[str, object]] = []

    async def _send_text(bot: object, chat_id: int, text: str, **kwargs: object) -> _NS:
        sent.append({"bot": bot, "chat_id": chat_id, "text": text, **kwargs})
        return _NS(id=77, message_id=77)

    async def _get_pending(_chat_id: int) -> None:
        return None

    async def _is_connected(_chat_id: int, *, fresh: bool = False) -> bool:
        return False

    async def _add_pending(*_args: object, **_kwargs: object) -> None:
        return None

    async def _locale(_update: object) -> str:
        return "en-US"

    monkeypatch.setattr(
        connect_added,
        "cfg",
        _NS(
            is_primary_group=lambda _chat_id: False,
            is_infrastructure_chat=lambda _chat_id: False,
        ),
    )
    monkeypatch.setattr(connect_added, "locale_for_update", _locale)
    monkeypatch.setattr(connect_added, "send_text", _send_text)
    monkeypatch.setattr(connect_added.db.groups_db, "get_pending", _get_pending)
    monkeypatch.setattr(connect_added.db.groups_db, "is_connected", _is_connected)
    monkeypatch.setattr(connect_added.db.groups_db, "add_pending", _add_pending)

    bot = _FakeBot()
    await connect_added.connection.on_bot_added(
        _forum_update(None),  # type: ignore[arg-type]
        _NS(bot=bot),  # type: ignore[arg-type]
    )

    assert len(sent) == 1
    assert sent[0]["chat_id"] == -1001234567890
    assert sent[0]["reply_markup"] is not None
    assert bot.sent == []  # no raw send_message path was used


@pytest.mark.asyncio
async def test_forum_prompt_records_the_adder_when_known(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A real admin who adds the bot is still recorded as the requester."""
    bot = _FakeBot()
    ctx = SimpleNamespace(bot=bot)
    recorded: list[tuple[int, str, int, int]] = []

    async def _get_pending(_chat_id: int) -> None:
        return None

    async def _is_connected(_chat_id: int, *, fresh: bool = False) -> bool:
        return False

    async def _add_pending(
        chat_id: int, title: str, owner_id: int, message_id: int
    ) -> None:
        recorded.append((chat_id, title, owner_id, message_id))

    async def _locale(_update: object) -> str:
        return "en-US"

    monkeypatch.setattr(
        connect_added,
        "cfg",
        SimpleNamespace(
            is_primary_group=lambda _chat_id: False,
            is_infrastructure_chat=lambda _chat_id: False,
        ),
    )
    monkeypatch.setattr(connect_added, "locale_for_update", _locale)
    monkeypatch.setattr(connect_added.db.groups_db, "get_pending", _get_pending)
    monkeypatch.setattr(connect_added.db.groups_db, "is_connected", _is_connected)
    monkeypatch.setattr(connect_added.db.groups_db, "add_pending", _add_pending)

    await connect_added.connection.on_bot_added(
        _forum_update(SimpleNamespace(id=4242)),  # type: ignore[arg-type]
        ctx,  # type: ignore[arg-type]
    )

    assert recorded == [(-1001234567890, "Community Forum", 4242, 77)]


def _promote_update(actor: object) -> SimpleNamespace:
    """Build the MY_CHAT_MEMBER update for an admin re-promoting the bot."""
    chat = SimpleNamespace(
        id=-1001234567890, type="supergroup", title="Community Forum"
    )
    cmc = SimpleNamespace(
        chat=chat,
        # * The actor identity is in from_user; the bot's own identity is not
        # * needed for the owner gate under test.
        new_chat_member=SimpleNamespace(status=ChatMemberStatus.ADMINISTRATOR),
        old_chat_member=SimpleNamespace(status=ChatMemberStatus.MEMBER),
        from_user=actor,
    )
    return SimpleNamespace(my_chat_member=cmc)


class _PromoteBot(_FakeBot):
    """Bot double whose member lookup reports one actor status."""

    def __init__(self, *, actor_status: ChatMemberStatus) -> None:
        super().__init__()
        self.me = SimpleNamespace(id=999, first_name="Bot", username="bot")
        self.actor_status = actor_status

    async def get_chat_member(self, chat_id: int, user_id: int) -> object:
        return SimpleNamespace(status=self.actor_status)


@pytest.mark.asyncio
async def test_repromote_by_an_admin_does_not_connect_the_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only the group owner's promotion may replay federation decisions."""
    joins: list[object] = []
    bot = _PromoteBot(actor_status=ChatMemberStatus.ADMINISTRATOR)

    async def _pending(_chat_id: int) -> dict[str, object]:
        return {"owner_id": 4242, "message_id": 77}

    async def _connected(_chat_id: int, *, fresh: bool = False) -> bool:
        return False

    async def _join(*args: object, **kwargs: object) -> bool:
        _ = (args, kwargs)
        joins.append(True)
        return False

    async def _locale(_update: object) -> str:
        return "en-US"

    async def _name(_uid: int, _fallback: str) -> str:
        return "Requester"

    async def _edit(*args: object, **kwargs: object) -> object:
        _ = (args, kwargs)
        return None

    async def _note(*args: object, **kwargs: object) -> str:
        _ = (args, kwargs)
        return ""

    monkeypatch.setattr(
        connect_added,
        "cfg",
        _NS(
            is_primary_group=lambda _chat_id: False,
            is_infrastructure_chat=lambda _chat_id: False,
        ),
    )
    monkeypatch.setattr(connect_added, "locale_for_update", _locale)
    monkeypatch.setattr(connect_added.db.groups_db, "get_pending", _pending)
    monkeypatch.setattr(connect_added.db.groups_db, "is_connected", _connected)
    monkeypatch.setattr(connect_added.db.users_cache, "get_first_name", _name)
    monkeypatch.setattr(connect_added, "safe_edit_message", _edit)
    monkeypatch.setattr(connect_added, "welcome_permission_note", _note)
    monkeypatch.setattr(
        connect_added.BuildConnection, "check_perms", lambda _self, _m: True
    )
    monkeypatch.setattr(connect_added.BuildConnection, "complete_join", _join)

    await connect_added.connection.on_bot_added(
        _promote_update(SimpleNamespace(id=4242)),
        _NS(bot=bot),  # type: ignore[arg-type]
    )

    assert joins == []


@pytest.mark.asyncio
async def test_repromote_by_the_owner_still_connects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The owner's re-promotion keeps the documented fast path."""
    joins: list[int] = []
    bot = _PromoteBot(actor_status=ChatMemberStatus.OWNER)

    async def _pending(_chat_id: int) -> dict[str, object]:
        return {"owner_id": 4242, "message_id": 77}

    async def _connected(_chat_id: int, *, fresh: bool = False) -> bool:
        return False

    async def _join(
        _self: object, chat_id: int, *_args: object, **_kwargs: object
    ) -> bool:
        joins.append(chat_id)
        return False

    async def _locale(_update: object) -> str:
        return "en-US"

    async def _name(_uid: int, _fallback: str) -> str:
        return "Owner"

    async def _edit(*args: object, **kwargs: object) -> object:
        _ = (args, kwargs)
        return None

    async def _note(*args: object, **kwargs: object) -> str:
        _ = (args, kwargs)
        return ""

    monkeypatch.setattr(
        connect_added,
        "cfg",
        _NS(
            is_primary_group=lambda _chat_id: False,
            is_infrastructure_chat=lambda _chat_id: False,
        ),
    )
    monkeypatch.setattr(connect_added, "locale_for_update", _locale)
    monkeypatch.setattr(connect_added.db.groups_db, "get_pending", _pending)
    monkeypatch.setattr(connect_added.db.groups_db, "is_connected", _connected)
    monkeypatch.setattr(connect_added.db.users_cache, "get_first_name", _name)
    monkeypatch.setattr(connect_added, "safe_edit_message", _edit)
    monkeypatch.setattr(connect_added, "welcome_permission_note", _note)
    monkeypatch.setattr(
        connect_added.BuildConnection, "check_perms", lambda _self, _m: True
    )
    monkeypatch.setattr(connect_added.BuildConnection, "complete_join", _join)

    await connect_added.connection.on_bot_added(
        _promote_update(SimpleNamespace(id=4242)),
        _NS(bot=bot),  # type: ignore[arg-type]
    )

    assert joins == [-1001234567890]


@pytest.mark.asyncio
async def test_join_decision_refuses_an_infrastructure_chat(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stale/tc_join tap inside a config chat must not connect it."""

    class _Query:
        def __init__(self) -> None:
            self.answers = 0

        async def answer(self) -> None:
            self.answers += 1

        @property
        def data(self) -> str:
            return "tc_join"

        @property
        def message(self) -> object:
            return None

    q = _Query()
    chat = _NS(id=-1004339701876, type="supergroup", title="Appeals")
    update = _NS(
        callback_query=q,
        effective_chat=chat,
        effective_user=_NS(id=42, first_name="Owner"),
        bot=_FakeBot(),
        user_data={},
    )
    monkeypatch.setattr(
        connect_added,
        "cfg",
        _NS(
            is_primary_group=lambda _chat_id: False,
            is_infrastructure_chat=lambda _chat_id: True,
        ),
    )

    await connect_added.connection.on_join_decision(update)  # type: ignore[arg-type]

    # * The guard answers the tap and returns before any member lookup or DB work.
    assert q.answers == 1


@pytest.mark.asyncio
async def test_stale_cancel_does_not_leave_a_connected_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A duplicate tc_cancel tap must not remove a live federation group."""

    class _Query:
        def __init__(self) -> None:
            self.answers = 0

        async def answer(self) -> None:
            self.answers += 1

        @property
        def data(self) -> str:
            return "tc_cancel"

        @property
        def message(self) -> object:
            return None

    q = _Query()
    chat = _NS(id=-1001234567890, type="supergroup", title="Connected")
    update = _NS(
        callback_query=q,
        effective_chat=chat,
        effective_user=_NS(id=42, first_name="Owner"),
        bot=_FakeBot(),
        user_data={},
    )

    class _Bot(_FakeBot):
        def __init__(self) -> None:
            super().__init__()
            self.left: list[int] = []

        async def get_chat_member(self, chat_id: int, user_id: int) -> object:
            return _NS(status=ChatMemberStatus.OWNER)

        async def leave_chat(self, chat_id: int) -> None:
            self.left.append(chat_id)

    bot = _Bot()
    update.bot = bot

    async def _locale(_update: object) -> str:
        return "en-US"

    async def _no_pending(_chat_id: int) -> None:
        return None

    async def _connected(_chat_id: int, *, fresh: bool = False) -> bool:
        return True

    monkeypatch.setattr(
        connect_added,
        "cfg",
        _NS(
            is_primary_group=lambda _chat_id: False,
            is_infrastructure_chat=lambda _chat_id: False,
        ),
    )
    monkeypatch.setattr(connect_added, "locale_for_update", _locale)
    monkeypatch.setattr(connect_added.db.groups_db, "get_pending", _no_pending)
    monkeypatch.setattr(connect_added.db.groups_db, "is_connected", _connected)

    await inspect.unwrap(connect_added.connection.on_join_decision)(
        update,  # type: ignore[arg-type]
        _NS(bot=bot),  # type: ignore[arg-type]
    )

    assert bot.left == [], "a stale cancel must not leave a connected group"


@pytest.mark.asyncio
async def test_channel_is_refused_before_any_telegram_or_db_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A channel has no member list; /tcconnect must refuse it, not store it."""
    message = _FakeMessage("channel")
    update = SimpleNamespace(
        effective_chat=message.chat,
        effective_user=SimpleNamespace(id=1, first_name="Admin", is_bot=False),
        effective_message=message,
    )
    ctx = SimpleNamespace(bot=_FakeBot())

    async def _locale(_update: object) -> str:
        return "en-US"

    monkeypatch.setattr(connect_module, "locale_for_update", _locale)

    await inspect.unwrap(connect_module.cmd_tcconnect)(update, ctx)

    assert len(message.replies) == 1
    assert "group" in message.replies[0].lower()


def _removal_update() -> SimpleNamespace:
    """Build the MY_CHAT_MEMBER update for the bot being removed."""
    chat = SimpleNamespace(id=-1001234567890, type="supergroup", title="Community")
    cmc = SimpleNamespace(
        chat=chat,
        new_chat_member=SimpleNamespace(status=ChatMemberStatus.LEFT),
        old_chat_member=SimpleNamespace(status=ChatMemberStatus.ADMINISTRATOR),
        from_user=None,
    )
    return SimpleNamespace(my_chat_member=cmc)


@pytest.mark.asyncio
async def test_bot_removal_reads_connection_before_deactivating(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The removal log must not depend on a read/write race."""
    order: list[str] = []
    logs: list[object] = []

    async def _is_connected(_chat_id: int, *, fresh: bool = False) -> bool:
        order.append("read-start")
        await asyncio.sleep(0)
        order.append("read-done")
        return True

    async def _deactivate(_chat_id: int) -> bool:
        order.append("deactivate")
        return True

    async def _remove_pending(_chat_id: int) -> None:
        order.append("remove_pending")

    async def _send_log(_bot: object, payload: object) -> None:
        logs.append(payload)

    async def _locale(_update: object) -> str:
        return "en-US"

    monkeypatch.setattr(
        connect_added,
        "cfg",
        _NS(
            is_primary_group=lambda _chat_id: False,
            is_infrastructure_chat=lambda _chat_id: False,
        ),
    )
    monkeypatch.setattr(connect_added, "locale_for_update", _locale)
    monkeypatch.setattr(connect_added.db.groups_db, "is_connected", _is_connected)
    monkeypatch.setattr(connect_added.db.groups_db, "deactivate_group", _deactivate)
    monkeypatch.setattr(connect_added.db.groups_db, "remove_pending", _remove_pending)
    monkeypatch.setattr(connect_added.messages, "send_log", _send_log)

    await connect_added.connection.on_bot_added(
        _removal_update(),  # type: ignore[arg-type]
        _NS(bot=_FakeBot()),  # type: ignore[arg-type]
    )

    assert order.index("read-done") < order.index("deactivate")
    assert order.index("deactivate") < order.index("remove_pending")
    assert len(logs) == 1


def test_connect_schedules_all_reads_while_resolving_the_bot_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A slow bot-id lookup must not delay the other independent reads."""
    started: list[str] = []
    identity_started = asyncio.Event()
    release_identity = asyncio.Event()

    class _Bot:
        async def get_chat_member(self, chat_id: int, user_id: int) -> object:
            return _NS(status=ChatMemberStatus.ADMINISTRATOR, privileges=_NS())

    async def _bot_identity() -> _NS:
        identity_started.set()
        await release_identity.wait()
        return _NS(id=999)

    async def _is_connected(_chat_id: int, *, fresh: bool = False) -> bool:
        started.append("is_connected")
        return False

    async def _pending(_chat_id: int) -> None:
        started.append("get_pending")

    async def _locale(_update: object) -> str:
        return "en-US"

    async def _join(*_args: object, **_kwargs: object) -> bool:
        return False

    async def _reply(*_args: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr(
        connect_module,
        "cfg",
        _NS(
            is_primary_group=lambda _chat_id: False,
            is_infrastructure_chat=lambda _chat_id: False,
        ),
    )
    monkeypatch.setattr(connect_module, "locale_for_update", _locale)
    monkeypatch.setattr(connect_module, "is_anon_admin", lambda _user: False)
    monkeypatch.setattr(connect_module.db.groups_db, "is_connected", _is_connected)
    monkeypatch.setattr(connect_module.db.groups_db, "get_pending", _pending)
    monkeypatch.setattr(
        connect_added.BuildConnection, "check_perms", lambda _self, _m: True
    )
    monkeypatch.setattr(connect_added.BuildConnection, "complete_join", _join)
    monkeypatch.setattr(connect_module, "reply_rich", _reply)

    message = _FakeMessage("supergroup")
    ctx = SimpleNamespace(
        effective_chat=message.chat,
        effective_user=SimpleNamespace(id=42, first_name="Admin", is_bot=False),
        effective_message=message,
        bot=_Bot(),
        bot_identity=_bot_identity,
    )

    body = connect_module.cmd_tcconnect
    while hasattr(body, "__wrapped__"):
        body = body.__wrapped__

    async def _scenario() -> None:
        running = asyncio.create_task(body(ctx))  # type: ignore[arg-type]
        await asyncio.wait_for(identity_started.wait(), timeout=1)
        assert started == ["is_connected", "get_pending"]
        release_identity.set()
        await running

    asyncio.run(_scenario())
