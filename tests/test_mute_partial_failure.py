# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Mute commit: a failed decision write leaves no state and no group touched."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from tcbot import database as db
from tcbot.modules.helper.pipelines import mute_flow
from tcbot.modules.helper.pipelines.mute_flow import execute_unmute
from tcbot.utils.formatter import user_ref
from tcbot.utils.i18n import Safe, t


class _FakeBot:
    """Bot double recording edits and restrictions, succeeding every call."""

    def __init__(self) -> None:
        self.edits: list[dict[str, Any]] = []
        self.restricts: list[dict[str, Any]] = []

    async def edit_message_text(self, *args: Any, **kwargs: Any) -> object:
        self.edits.append({"args": args, "kwargs": kwargs})
        return object()

    async def restrict_chat_member(self, *args: Any, **kwargs: Any) -> bool:
        self.restricts.append({"args": args, "kwargs": kwargs})
        return True

    async def send_message(self, *args: Any, **kwargs: Any) -> object:
        return object()


class _FakeChat:
    id = 22


class _FakeUpdate:
    """Update double exposing effective_chat like the mute executor needs."""

    def __init__(self) -> None:
        self.effective_chat = _FakeChat()


def _meta() -> dict[str, Any]:
    return {
        "mute_target_id": 33,
        "mute_admin_id": 1,
        "mute_target_fname": "Target",
        "mute_reason": "spam",
        "mute_duration": timedelta(hours=1),
        "mute_proof_msgs": None,
        "mute_prompt_chat": 22,
        "mute_prompt_id": 44,
    }


@pytest.fixture
def _mute_no_io(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub locale, group fetch, and demote re-check so no database is touched."""

    async def _locale(_update: Any) -> str:
        return "en-US"

    async def _no_groups() -> list[dict[str, Any]]:
        return []

    async def _role(user_id: int, *, fresh: bool = False) -> str | None:
        # * The executor is a Moderator; the target holds no role, so the
        # * enforcement-time rank check passes.
        return "moderator" if user_id == 1 else None

    monkeypatch.setattr(mute_flow, "locale_for_update", _locale)
    monkeypatch.setattr(db.groups_db, "active_groups", _no_groups)
    monkeypatch.setattr(db.users_roles, "get_effective_role", _role)


def _run(bot: _FakeBot) -> None:
    asyncio.run(
        mute_flow._execute_mute(
            bot,  # type: ignore[arg-type]
            _FakeUpdate(),  # type: ignore[arg-type]
            _meta(),  # type: ignore[arg-type]
        )
    )


def _expected_db_fail() -> str:
    return t(
        "muting.note.db_fail",
        "en-US",
        user=Safe(user_ref(33, "Target")),
    )


def test_the_decision_write_failure_leaves_every_group_untouched(
    _mute_no_io: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed decision write must not restrict a single group.

    The decision and the case that holds it are one transaction, so a
    failure leaves no mute behind. The groups are only restricted after
    the decision landed, so they stay untouched as well.
    """

    async def _groups() -> list[dict[str, Any]]:
        return [{"chat_id": 101, "title": "Group A"}]

    async def _record(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("decision write down")

    monkeypatch.setattr(db.groups_db, "active_groups", _groups)
    monkeypatch.setattr(db.mutes_db, "record_mute", _record)

    bot = _FakeBot()
    _run(bot)

    assert bot.restricts == []
    assert len(bot.edits) == 1
    assert bot.edits[0]["kwargs"]["chat_id"] == 22
    assert bot.edits[0]["kwargs"]["message_id"] == 44
    assert bot.edits[0]["args"][0] == _expected_db_fail()


def test_a_cancelled_decision_propagates_without_touching_a_group(
    _mute_no_io: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A cancelled decision propagates and leaves no group restricted."""

    async def _record(*args: Any, **kwargs: Any) -> None:
        raise asyncio.CancelledError()

    monkeypatch.setattr(db.mutes_db, "record_mute", _record)

    bot = _FakeBot()
    with pytest.raises(asyncio.CancelledError):
        _run(bot)

    assert bot.restricts == []
    assert bot.edits == []


def test_the_decision_write_failure_is_not_reported_as_success(
    _mute_no_io: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The moderator has to see that the mute did not land."""

    async def _record(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("decision write down")

    monkeypatch.setattr(db.mutes_db, "record_mute", _record)

    bot = _FakeBot()
    _run(bot)

    assert len(bot.edits) == 1
    assert bot.edits[0]["args"][0] == _expected_db_fail()


# ─────────────── Unmute total failure keeps its delivery run ────────────── #


class _UnmuteMsg:
    def __init__(self) -> None:
        self.replies: list[str] = []

    async def reply_text(self, text: str, *args: Any, **kwargs: Any) -> None:
        self.replies.append(text)


class _UnmuteUser:
    id = 7
    first_name = "Mod"


class _UnmuteUpdate:
    def __init__(self, msg: _UnmuteMsg) -> None:
        self.effective_message = msg
        self.effective_user = _UnmuteUser()
        self.effective_chat = _FakeChat()


class _UnmuteCtx:
    def __init__(self, bot: Any) -> None:
        self.bot = bot


def test_unmute_total_failure_keeps_its_delivery_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The revoked record keeps the failed groups through the run.

    The revocation and the run are one decision, so a delivery that failed
    everywhere is still retried by the worker instead of leaving the user
    muted in every group with no record to repair from.
    """

    async def _locale(_update: Any) -> str:
        return "en-US"

    async def _active_mute(user_id: int) -> dict[str, Any]:
        return {"user_id": user_id, "until_date": None}

    async def _groups() -> list[dict[str, Any]]:
        return [
            {"chat_id": 101, "title": "Group A"},
            {"chat_id": 102, "title": "Group B"},
        ]

    revoked: list[tuple[int, int, list[int]]] = []

    async def _revoke(
        user_id: int, requested_by: int, chat_ids: list[int]
    ) -> tuple[int, int]:
        revoked.append((user_id, requested_by, chat_ids))
        return 1, 55

    async def _report(run_id: int) -> dict[str, Any]:
        return {
            "id": run_id,
            "target_count": 3,
            "failed_count": 3,
            "succeeded_count": 0,
            "skipped_count": 0,
            "targets": [
                {"chat_id": 101, "status": "failed", "title": "Group A"},
                {"chat_id": 102, "status": "failed", "title": "Group B"},
                {"chat_id": -1, "status": "failed", "title": "Primary"},
            ],
        }

    async def _deliver(bot: Any, run_id: int) -> bool:
        return True

    monkeypatch.setattr(mute_flow, "locale_for_update", _locale)
    monkeypatch.setattr(
        mute_flow, "cfg", SimpleNamespace(main_group=-1, logs=(-3, None))
    )
    monkeypatch.setattr(db.mutes_db, "get_active_mute", _active_mute)
    monkeypatch.setattr(db.groups_db, "active_groups", _groups)
    monkeypatch.setattr(db.mutes_db, "revoke_mute_and_queue_unmute", _revoke)
    monkeypatch.setattr(db.enforcement_db, "run_report", _report)
    monkeypatch.setattr(mute_flow.enforcement_worker, "deliver_queued_run", _deliver)

    msg = _UnmuteMsg()
    asyncio.run(
        execute_unmute(
            _UnmuteUpdate(msg),  # type: ignore[arg-type]
            _UnmuteCtx(_FakeBot()),  # type: ignore[arg-type]
            33,
            "Target",
        )
    )

    assert revoked == [(33, 7, [101, 102, -1])]
    assert len(msg.replies) == 1
    assert "could not be unmuted yet" in msg.replies[0]
