# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""The protected-target gate runs once, before the durable mute is committed."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any

import pytest

from tcbot import database as db
from tcbot.modules.helper.pipelines import mute_flow


class _FakeBot:
    def __init__(self) -> None:
        self.edits: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
        self.restricts: list[tuple[Any, ...]] = []

    async def edit_message_text(self, *args: Any, **kwargs: Any) -> object:
        self.edits.append((args, kwargs))
        return object()

    async def restrict_chat_member(self, *args: Any, **kwargs: Any) -> bool:
        self.restricts.append(args)
        return True

    async def send_message(self, *args: Any, **kwargs: Any) -> object:
        return object()


class _FakeChat:
    id = 22


class _FakeUpdate:
    effective_chat = _FakeChat()


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


def test_a_late_owner_verdict_cannot_hide_a_committed_mute(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A post-commit owner verdict must not suppress the queued delivery.

    The mute decision and its durable run are written together. Once that
    write succeeds, a later protected-target check cannot retract the run,
    so the executor must not return as if the action had been refused. The
    only authoritative gate is the one before the decision write.
    """

    async def _locale(_update: Any) -> str:
        return "en-US"

    async def _groups() -> list[dict[str, Any]]:
        return [{"chat_id": 101, "title": "Group A"}]

    async def _role(user_id: int, *, fresh: bool = False) -> str | None:
        return "moderator" if user_id == 1 else None

    gate_calls: list[int] = []

    async def _demote(*args: Any, **kwargs: Any) -> str:
        gate_calls.append(1)
        # * The first call is the pre-write gate; a second call models the
        # * late promotion that the old post-write check claimed to stop.
        return "moderator" if len(gate_calls) == 1 else "owner"

    written: list[tuple[Any, ...]] = []

    async def _record(*args: Any, **kwargs: Any) -> tuple[int, int]:
        written.append(args)
        return 1, 55

    delivered: list[int] = []

    async def _deliver(_bot: Any, run_id: int) -> bool:
        delivered.append(run_id)
        return True

    async def _report(run_id: int) -> dict[str, Any]:
        return {
            "id": run_id,
            "target_count": 1,
            "failed_count": 0,
            "succeeded_count": 1,
            "skipped_count": 0,
            "targets": [
                {"chat_id": 101, "status": "succeeded", "title": "Group A"},
            ],
        }

    async def _send_log(*args: Any, **kwargs: Any) -> object:
        return object()

    monkeypatch.setattr(mute_flow, "locale_for_update", _locale)
    monkeypatch.setattr(db.groups_db, "active_groups", _groups)
    monkeypatch.setattr(db.users_roles, "get_effective_role", _role)
    monkeypatch.setattr(mute_flow, "demote_before_enforcement", _demote)
    monkeypatch.setattr(db.mutes_db, "record_mute", _record)
    monkeypatch.setattr(mute_flow.enforcement_worker, "deliver_queued_run", _deliver)
    monkeypatch.setattr(db.enforcement_db, "run_report", _report)
    monkeypatch.setattr(mute_flow, "send_log", _send_log)

    bot = _FakeBot()
    asyncio.run(
        mute_flow._execute_mute(
            bot,  # type: ignore[arg-type]
            _FakeUpdate(),  # type: ignore[arg-type]
            _meta(),  # type: ignore[arg-type]
        )
    )

    assert len(gate_calls) == 1
    assert len(written) == 1
    assert delivered == [55]
    assert bot.restricts == []
