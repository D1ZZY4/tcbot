# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""execute_unmute records the decision and its durable delivery together."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, cast

import pytest

from tcbot import database as db
from tcbot import enforcement_worker
from tcbot.modules.helper.messages import replies
from tcbot.modules.helper.pipelines import mute_actions
from tcbot.utils.i18n import Safe, t, user_ref


class _FakeMsg:
    """Message double recording replies."""

    def __init__(self) -> None:
        self.replies: list[str] = []

    async def reply_text(self, text: str, **kwargs: Any) -> object:
        self.replies.append(text)
        return object()


class _FakeBot:
    """Bot double recording log sends; the worker owns the restrict calls."""

    def __init__(self) -> None:
        self.logs: list[str] = []

    async def send_message(self, chat_id: int, text: str, **kwargs: Any) -> object:
        self.logs.append(text)
        return object()


def _report(targets: list[dict[str, Any]]) -> dict[str, Any]:
    """Build the run-report shape the enforcement helpers read."""
    failed = sum(1 for target in targets if target["status"] == "failed")
    return {
        "id": 1,
        "target_count": len(targets),
        "succeeded_count": sum(
            1 for target in targets if target["status"] == "succeeded"
        ),
        "failed_count": failed,
        "skipped_count": sum(1 for target in targets if target["status"] == "skipped"),
        "targets": targets,
    }


def _install(
    monkeypatch: pytest.MonkeyPatch,
    *,
    mute: Any = "default",
    groups: Any = "default",
    revoke: Any = "default",
    report: dict[str, Any] | None = None,
    deliver_fails: bool = False,
) -> dict[str, list[Any]]:
    """Stub the locale, config, database, and worker seams."""
    calls: dict[str, list[Any]] = {
        "revoke": [],
        "deliver": [],
        "reports": [],
    }

    async def _locale(update: object) -> str:
        return "en-US"

    async def _get_active_mute(user_id: int) -> Any:
        if isinstance(mute, BaseException):
            raise mute
        if mute == "default":
            return {"user_id": user_id}
        return mute

    async def _active_groups() -> Any:
        if isinstance(groups, BaseException):
            raise groups
        return groups

    async def _revoke(user_id: int, requested_by: int, chat_ids: list[int]) -> Any:
        calls["revoke"].append((user_id, requested_by, chat_ids))
        if isinstance(revoke, BaseException):
            raise revoke
        if revoke == "default":
            return 1, 7
        return revoke

    async def _deliver(bot: object, run_id: int) -> bool:
        calls["deliver"].append(run_id)
        if deliver_fails:
            raise RuntimeError("worker down")
        return True

    async def _run_report(run_id: int) -> dict[str, Any] | None:
        calls["reports"].append(run_id)
        return report

    monkeypatch.setattr(mute_actions, "locale_for_update", _locale)
    monkeypatch.setattr(
        mute_actions,
        "cfg",
        SimpleNamespace(main_group=-1, exec_group=-2, logs=(-3, None)),
    )
    monkeypatch.setattr(db.mutes_db, "get_active_mute", _get_active_mute)
    monkeypatch.setattr(db.mutes_db, "revoke_mute_and_queue_unmute", _revoke)
    monkeypatch.setattr(db.groups_db, "active_groups", _active_groups)
    monkeypatch.setattr(enforcement_worker, "deliver_queued_run", _deliver)
    monkeypatch.setattr(db.enforcement_db, "run_report", _run_report)
    return calls


def _update(msg: _FakeMsg) -> Any:
    admin = SimpleNamespace(id=9, first_name="Admin")
    return SimpleNamespace(effective_message=msg, effective_user=admin)


def _ctx(bot: _FakeBot) -> Any:
    return cast("Any", SimpleNamespace(bot=bot))


def _retry() -> str:
    return replies.err_db_retry("en-US", plain=True)


def _no_mute() -> str:
    return t("muting.note.no_mute", "en-US", user=Safe(user_ref(42, "T")))


def test_no_mute_replies_without_revoking_or_queueing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _install(monkeypatch, mute=None, groups=[])
    msg, bot = _FakeMsg(), _FakeBot()
    asyncio.run(mute_actions.execute_unmute(_update(msg), _ctx(bot), 42, "T"))
    assert calls["revoke"] == []
    assert calls["deliver"] == []
    assert msg.replies == [_no_mute()]


def test_read_failure_replies_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _install(monkeypatch, mute=RuntimeError("db down"), groups=[])
    msg, bot = _FakeMsg(), _FakeBot()
    asyncio.run(mute_actions.execute_unmute(_update(msg), _ctx(bot), 42, "T"))
    assert calls["revoke"] == []
    assert msg.replies == [_retry()]


def test_groups_failure_keeps_the_record_for_a_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _install(monkeypatch, groups=RuntimeError("db down"))
    msg, bot = _FakeMsg(), _FakeBot()
    asyncio.run(mute_actions.execute_unmute(_update(msg), _ctx(bot), 42, "T"))
    assert calls["revoke"] == []
    assert msg.replies == [_retry()]


def test_a_failed_revocation_reports_a_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _install(
        monkeypatch,
        groups=[{"chat_id": 5, "title": "G"}],
        revoke=RuntimeError("db down"),
    )
    msg, bot = _FakeMsg(), _FakeBot()
    asyncio.run(mute_actions.execute_unmute(_update(msg), _ctx(bot), 42, "T"))
    assert calls["deliver"] == []
    assert msg.replies == [_retry()]


def test_a_lost_race_reports_no_mute(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _install(
        monkeypatch,
        groups=[{"chat_id": 5, "title": "G"}],
        revoke=(0, None),
    )
    msg, bot = _FakeMsg(), _FakeBot()
    asyncio.run(mute_actions.execute_unmute(_update(msg), _ctx(bot), 42, "T"))
    assert calls["deliver"] == []
    assert msg.replies == [_no_mute()]


def test_the_run_targets_every_group_including_the_primary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _install(
        monkeypatch,
        groups=[{"chat_id": 5, "title": "G"}],
        report=_report(
            [
                {"chat_id": 5, "status": "succeeded", "title": "G"},
                {"chat_id": -1, "status": "succeeded", "title": "P"},
            ]
        ),
    )
    msg, bot = _FakeMsg(), _FakeBot()
    asyncio.run(mute_actions.execute_unmute(_update(msg), _ctx(bot), 42, "T"))
    assert calls["revoke"] == [(42, 9, [5, -1])]
    assert calls["deliver"] == [7]


def test_a_full_restore_announces_completion(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(
        monkeypatch,
        groups=[{"chat_id": 5, "title": "G"}],
        report=_report(
            [
                {"chat_id": 5, "status": "succeeded", "title": "G"},
                {"chat_id": -1, "status": "succeeded", "title": "P"},
            ]
        ),
    )
    msg, bot = _FakeMsg(), _FakeBot()
    asyncio.run(mute_actions.execute_unmute(_update(msg), _ctx(bot), 42, "T"))
    assert len(msg.replies) == 1
    assert "has been unmuted" in msg.replies[0]
    assert "2/2" in msg.replies[0]


def test_a_partial_restore_names_the_failed_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install(
        monkeypatch,
        groups=[{"chat_id": 5, "title": "G"}, {"chat_id": 6, "title": "H"}],
        report=_report(
            [
                {"chat_id": 5, "status": "succeeded", "title": "G"},
                {"chat_id": 6, "status": "failed", "title": "H"},
                {"chat_id": -1, "status": "succeeded", "title": "P"},
            ]
        ),
    )
    msg, bot = _FakeMsg(), _FakeBot()
    asyncio.run(mute_actions.execute_unmute(_update(msg), _ctx(bot), 42, "T"))
    assert len(msg.replies) == 1
    assert "some groups only" in msg.replies[0]
    assert "2/3" in msg.replies[0]


def test_a_total_failure_reports_every_group(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(
        monkeypatch,
        groups=[{"chat_id": 5, "title": "G"}],
        report=_report(
            [
                {"chat_id": 5, "status": "failed", "title": "G"},
                {"chat_id": -1, "status": "failed", "title": "P"},
            ]
        ),
    )
    msg, bot = _FakeMsg(), _FakeBot()
    asyncio.run(mute_actions.execute_unmute(_update(msg), _ctx(bot), 42, "T"))
    assert len(msg.replies) == 1
    assert "could not be unmuted yet" in msg.replies[0]
    assert "2/2" in msg.replies[0]


def test_an_unsettled_run_is_reported_as_queued(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install(
        monkeypatch,
        groups=[{"chat_id": 5, "title": "G"}],
        report=_report(
            [
                {"chat_id": 5, "status": "succeeded", "title": "G"},
                {"chat_id": -1, "status": "pending", "title": "P"},
            ]
        ),
    )
    msg, bot = _FakeMsg(), _FakeBot()
    asyncio.run(mute_actions.execute_unmute(_update(msg), _ctx(bot), 42, "T"))
    assert len(msg.replies) == 1
    assert "queued" in msg.replies[0]


def test_a_run_without_a_report_is_reported_as_queued(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install(monkeypatch, groups=[{"chat_id": 5, "title": "G"}], report=None)
    msg, bot = _FakeMsg(), _FakeBot()
    asyncio.run(mute_actions.execute_unmute(_update(msg), _ctx(bot), 42, "T"))
    assert len(msg.replies) == 1
    assert "queued" in msg.replies[0]


def test_an_unmute_without_a_connected_group_closes_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _install(
        monkeypatch,
        groups=[],
        report=_report([]),
    )
    monkeypatch.setattr(
        mute_actions, "cfg", SimpleNamespace(main_group=0, logs=(-3, None))
    )
    msg, bot = _FakeMsg(), _FakeBot()
    asyncio.run(mute_actions.execute_unmute(_update(msg), _ctx(bot), 42, "T"))
    assert calls["revoke"] == [(42, 9, [])]
    assert len(msg.replies) == 1
    assert "has been unmuted" in msg.replies[0]
    assert "No connected groups configured" in msg.replies[0]


def test_a_failed_inline_delivery_stays_queued(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _install(
        monkeypatch,
        groups=[{"chat_id": 5, "title": "G"}],
        deliver_fails=True,
        report=_report([{"chat_id": 5, "status": "pending", "title": "G"}]),
    )
    msg, bot = _FakeMsg(), _FakeBot()
    asyncio.run(mute_actions.execute_unmute(_update(msg), _ctx(bot), 42, "T"))
    assert calls["reports"] == [7]
    assert len(msg.replies) == 1
    assert "queued" in msg.replies[0]
