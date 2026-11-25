# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Group connect enforcement replay: happy path, blind outage, truncation."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from pyrogram.errors import BadRequest

from tcbot import database as db
from tcbot.modules.helper.pipelines import connect_common, connect_replay
from tcbot.modules.helper.pipelines.connect_added import BuildConnection
from tcbot.modules.helper.pipelines.connect_replay import (
    _REPLAY_CAP,
    _REPLAY_QUEUE_ATTEMPTS,
)


@pytest.fixture(autouse=True)
def _replay_targets_are_not_owners(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make replayed decisions concern ordinary users in these tests."""

    async def _is_owner(_user_id: int, *, fresh: bool = False) -> bool:
        _ = fresh
        return False

    monkeypatch.setattr(db.users_roles, "is_owner", _is_owner)


class _FakeBot:
    def __init__(self) -> None:
        self.id: int = 999
        self.banned: list[int] = []
        self.restricted: list[int] = []
        self.sent: list[tuple[int, str]] = []
        self.fail_ban: dict[int, BadRequest] = {}
        self.chat_member_payload: dict[str, Any] = {}

    async def get_chat_member(self, chat_id: int, user_id: int) -> Any:
        return type(
            "Member",
            (),
            {"privileges": type("P", (), self.chat_member_payload)()},
        )()

    async def get_chat(self, chat_id: int) -> Any:
        return type("C", (), {"username": None})()

    async def get_chat_administrators(self, chat_id: int) -> list[Any]:
        return []

    async def ban_chat_member(self, chat_id: int, user_id: int) -> None:
        failure = self.fail_ban.get(user_id)
        if failure is not None:
            raise failure
        self.banned.append(user_id)

    async def restrict_chat_member(self, *args: Any, **kwargs: Any) -> None:
        self.restricted.append(int(args[1]))

    async def send_message(self, chat_id: int, text: str, **kwargs: Any) -> None:
        self.sent.append((chat_id, text))


def _install_world(
    monkeypatch: pytest.MonkeyPatch,
    *,
    ban_uids: list[int] | None = None,
    mute_docs: list[Any] | None = None,
) -> list[tuple[int, list[int], int | None]]:
    async def _ban_uids() -> list[int]:
        return list(ban_uids) if ban_uids is not None else []

    async def _mute_docs() -> list[Any]:
        return list(mute_docs) if mute_docs is not None else []

    async def _add_group(*args: Any, **kwargs: Any) -> None:
        return None

    async def _remove_pending(chat_id: int) -> None:
        return None

    queued: list[tuple[int, list[int], int | None]] = []

    async def _queue_replay(
        chat_id: int, user_ids: list[int], requested_by_user_id: int | None
    ) -> int:
        queued.append((chat_id, list(user_ids), requested_by_user_id))
        return len(user_ids)

    monkeypatch.setattr(db.bans_db, "active_ban_user_ids", _ban_uids)
    monkeypatch.setattr(db.mutes_db, "active_mute_docs", _mute_docs)
    monkeypatch.setattr(db.groups_db, "add_group", _add_group)
    monkeypatch.setattr(db.groups_db, "remove_pending", _remove_pending)
    monkeypatch.setattr(db.enforcement_db, "queue_connect_replay", _queue_replay)
    return queued


def _join() -> BuildConnection:
    return BuildConnection(community_name="TCF")


def test_complete_join_happy_path_is_not_blind(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queued = _install_world(monkeypatch, ban_uids=[11, 22])
    bot = _FakeBot()
    blind = asyncio.run(_join().complete_join(-100, "Group", 1, "Owner", bot))  # type: ignore[arg-type]
    assert blind is False
    assert sorted(bot.banned) == [11, 22]
    assert bot.sent != []
    assert queued == []


def test_complete_join_refuses_to_activate_when_the_decision_store_is_down(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unknown bans are not an empty list, so the connect must fail closed."""

    async def _ban_boom() -> list[int]:
        raise RuntimeError("ban store down")

    async def _mute_boom() -> list[Any]:
        raise RuntimeError("mute store down")

    _install_world(monkeypatch)
    monkeypatch.setattr(db.bans_db, "active_ban_user_ids", _ban_boom)
    monkeypatch.setattr(db.mutes_db, "active_mute_docs", _mute_boom)
    activated: list[int] = []

    async def _add_group(chat_id: int, *_args: Any) -> None:
        activated.append(chat_id)

    monkeypatch.setattr(db.groups_db, "add_group", _add_group)

    with pytest.raises(RuntimeError, match="cannot read federation decisions"):
        asyncio.run(_join().complete_join(-100, "Group", 1, "Owner", _FakeBot()))  # type: ignore[arg-type]

    assert activated == []


def test_a_protected_owner_is_not_replayed_into_the_new_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A decision filed before a promotion must not ban the Owner at connect."""
    queued = _install_world(monkeypatch, ban_uids=[11, 22])

    async def _owner(user_id: int, *, fresh: bool = False) -> bool:
        assert fresh is True
        return user_id == 22

    monkeypatch.setattr(db.users_roles, "is_owner", _owner)
    bot = _FakeBot()

    blind = asyncio.run(_join().complete_join(-100, "Group", 1, "Owner", bot))  # type: ignore[arg-type]

    assert blind is False
    assert bot.banned == [11]
    assert queued == []


def test_an_unverifiable_role_refuses_connect_activation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An Owner lookup outage must not activate an unenforced group."""
    _install_world(monkeypatch, ban_uids=[11])
    activated: list[int] = []

    async def _add_group(chat_id: int, *_args: Any) -> None:
        activated.append(chat_id)

    async def _broken_role(_user_id: int, *, fresh: bool = False) -> bool:
        raise RuntimeError("role store unavailable")

    monkeypatch.setattr(db.groups_db, "add_group", _add_group)
    monkeypatch.setattr(db.users_roles, "is_owner", _broken_role)

    with pytest.raises(RuntimeError, match="cannot verify protected role"):
        asyncio.run(_join().complete_join(-100, "Group", 1, "Owner", _FakeBot()))  # type: ignore[arg-type]

    assert activated == []


def test_complete_join_truncates_replay_and_is_blind(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    uids = list(range(_REPLAY_CAP + 1))
    queued = _install_world(monkeypatch, ban_uids=uids)
    bot = _FakeBot()
    blind = asyncio.run(_join().complete_join(-100, "Group", 1, "Owner", bot))  # type: ignore[arg-type]
    assert blind is True
    assert len(bot.banned) == _REPLAY_CAP
    assert queued == [(-100, [uids[-1]], 1)]


def test_complete_join_stops_at_the_replay_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The replay must not run past its time budget.

    Telegram paces same-chat requests at 20 a minute, so an unbounded
    replay kept the connect handler running for a quarter of an hour.
    The unreached users become durable work instead of being lost.
    """
    monkeypatch.setattr(connect_replay, "_REPLAY_BUDGET_S", 0.0)
    queued = _install_world(monkeypatch, ban_uids=[11, 22, 33])
    bot = _FakeBot()
    blind = asyncio.run(_join().complete_join(-100, "Group", 1, "Owner", bot))  # type: ignore[arg-type]
    assert blind is True
    assert bot.banned == []
    assert queued == [(-100, [11, 22, 33], 1)]


def test_a_failed_replay_is_queued_not_dropped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A refused ban did not land, so the connect must keep it as work.

    The replay used to advance past every request in the chunk, which
    turned a transient Telegram refusal into a member who stayed
    unrestricted in the new group.
    """
    queued = _install_world(monkeypatch, ban_uids=[11, 22])
    bot = _FakeBot()
    bot.fail_ban[22] = BadRequest("CHAT_ADMIN_REQUIRED")
    blind = asyncio.run(_join().complete_join(-100, "Group", 1, "Owner", bot))  # type: ignore[arg-type]
    assert blind is True
    assert bot.banned == [11]
    assert queued == [(-100, [22], 1)]


def test_a_benign_replay_refusal_is_not_queued(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A user who was never in the chat needs no durable retry."""
    queued = _install_world(monkeypatch, ban_uids=[11])
    bot = _FakeBot()
    bot.fail_ban[11] = BadRequest("USER_NOT_PARTICIPANT")
    blind = asyncio.run(_join().complete_join(-100, "Group", 1, "Owner", bot))  # type: ignore[arg-type]
    assert blind is False
    assert queued == []


def test_a_transient_replay_queue_failure_is_retried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A short database blip must not drop the unapplied remainder."""
    monkeypatch.setattr(connect_replay, "_REPLAY_QUEUE_BACKOFF", 0.0)
    attempts = 0

    async def _flaky_queue(chat_id: int, user_ids: list[int], by: int | None) -> int:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("transient db blip")
        return len(user_ids)

    queued = _install_world(monkeypatch, ban_uids=[11, 22, 33])
    monkeypatch.setattr(connect_replay, "_REPLAY_BUDGET_S", 0.0)
    monkeypatch.setattr(db.enforcement_db, "queue_connect_replay", _flaky_queue)
    bot = _FakeBot()

    blind = asyncio.run(_join().complete_join(-100, "Group", 1, "Owner", bot))  # type: ignore[arg-type]

    assert blind is True
    assert attempts == 2
    assert queued == []


def test_an_exhausted_replay_queue_failure_is_surfaced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An active group must never silently miss federation decisions."""
    monkeypatch.setattr(connect_replay, "_REPLAY_QUEUE_BACKOFF", 0.0)
    attempts = 0

    async def _broken_queue(chat_id: int, user_ids: list[int], by: int | None) -> int:
        nonlocal attempts
        attempts += 1
        raise RuntimeError("db down")

    _install_world(monkeypatch, ban_uids=[11, 22, 33])
    monkeypatch.setattr(connect_replay, "_REPLAY_BUDGET_S", 0.0)
    monkeypatch.setattr(db.enforcement_db, "queue_connect_replay", _broken_queue)
    bot = _FakeBot()

    with pytest.raises(RuntimeError, match="connect replay queue failed"):
        asyncio.run(_join().complete_join(-100, "Group", 1, "Owner", bot))  # type: ignore[arg-type]

    assert attempts == _REPLAY_QUEUE_ATTEMPTS


def test_a_failed_replay_undoes_the_activation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed queue write must not leave an active, unenforced group."""
    monkeypatch.setattr(connect_replay, "_REPLAY_QUEUE_BACKOFF", 0.0)

    async def _broken_queue(chat_id: int, user_ids: list[int], by: int | None) -> int:
        raise RuntimeError("db down")

    deactivated: list[int] = []

    async def _deactivate(chat_id: int) -> bool:
        deactivated.append(chat_id)
        return True

    _install_world(monkeypatch, ban_uids=[11, 22, 33])
    monkeypatch.setattr(connect_replay, "_REPLAY_BUDGET_S", 0.0)
    monkeypatch.setattr(db.enforcement_db, "queue_connect_replay", _broken_queue)
    monkeypatch.setattr(db.groups_db, "deactivate_group", _deactivate)

    with pytest.raises(RuntimeError, match="connect replay queue failed"):
        asyncio.run(_join().complete_join(-100, "Group", 1, "Owner", _FakeBot()))  # type: ignore[arg-type]

    assert deactivated == [-100]


def test_a_missing_welcome_permission_is_reported() -> None:
    """The new Bot API right is surfaced to the owner, not silently ignored."""
    bot = _FakeBot()
    bot.chat_member_payload = {"can_send_welcome_messages": False}

    note = asyncio.run(
        connect_common.welcome_permission_note(bot, -100, "en-US")  # type: ignore[arg-type]
    )

    assert "Welcome Messages" in note


def test_a_granted_welcome_permission_has_no_note() -> None:
    bot = _FakeBot()
    bot.chat_member_payload = {"can_send_welcome_messages": True}

    note = asyncio.run(
        connect_common.welcome_permission_note(bot, -100, "en-US")  # type: ignore[arg-type]
    )

    assert note == ""


def test_an_older_server_without_the_field_has_no_note() -> None:
    bot = _FakeBot()
    bot.chat_member_payload = {"status": "administrator"}

    note = asyncio.run(
        connect_common.welcome_permission_note(bot, -100, "en-US")  # type: ignore[arg-type]
    )

    assert note == ""


def test_a_welcome_permission_probe_failure_has_no_note() -> None:
    bot = _FakeBot()

    async def _boom(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("telegram down")

    bot.get_chat_member = _boom  # type: ignore[method-assign]
    note = asyncio.run(
        connect_common.welcome_permission_note(bot, -100, "en-US")  # type: ignore[arg-type]
    )

    assert note == ""
