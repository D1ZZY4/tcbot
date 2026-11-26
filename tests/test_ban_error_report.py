# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""A queued ban with failed groups ships the reason to the error channel."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from tcbot import database as db
from tcbot.modules.helper import guards, messages
from tcbot.modules.helper.pipelines import ban_executor, moderation_enforcement


class _Log:
    def __init__(self) -> None:
        self.errors: list[tuple[str, dict[str, Any]]] = []

    def debug(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def info(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def warning(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def exception(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def error(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self.errors.append((msg % args if args else msg, kwargs))


class _Bot:
    username = "testbot"


def _meta() -> dict[str, Any]:
    return {
        "ban_target_id": 33,
        "ban_target_fname": "Target",
        "ban_reason": "spam",
        "ban_admin_id": 44,
        "ban_admin_fname": "Mod",
        "ban_prompt_msg_id": 0,
        "ban_prompt_chat_id": 0,
        "ban_locale": "en-US",
    }


@pytest.mark.asyncio
async def test_a_partial_enforcement_reports_its_actual_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log = _Log()
    monkeypatch.setattr(ban_executor, "log", log)
    # * The shared runner owns the operator-facing partial-failure report.
    monkeypatch.setattr(moderation_enforcement, "log", log)

    async def _refusal(*_args: Any, **_kwargs: Any) -> None:
        return None

    async def _groups() -> list[dict[str, Any]]:
        return [{"chat_id": -100}, {"chat_id": -200}]

    async def _none(*_args: Any, **_kwargs: Any) -> Any:
        return None

    async def _identity(*_args: Any, **_kwargs: Any) -> Any:
        return SimpleNamespace(username="testbot")

    async def _upload(*_args: Any, **_kwargs: Any) -> Any:
        return SimpleNamespace(
            message_id=5,
            link="https://t.me/c/1/5",
            expected_item_count=0,
            items=[],
            landed=True,
            documents=list,
        )

    async def _record(*_args: Any, **_kwargs: Any) -> tuple[int, bool, str, int]:
        return 7, True, "ban00000001", 23

    async def _report(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        return {"id": 23}

    def _failed_targets(_report: Any) -> list[dict[str, Any]]:
        return [
            {
                "chat_id": -100,
                "title": "Group",
                "last_error_detail": "CHAT_ADMIN_REQUIRED",
            }
        ]

    def _outcome(_report: Any, _total: int) -> Any:
        return SimpleNamespace(total=2, applied=1, failed=1, pending=0)

    monkeypatch.setattr(guards, "enforcement_refusal", _refusal)
    monkeypatch.setattr(db.groups_db, "active_groups", _groups)
    monkeypatch.setattr(ban_executor, "locale_for_user", _none)
    monkeypatch.setattr(db.bans_db, "get_active_ban", _none)
    monkeypatch.setattr(ban_executor, "bot_identity", _identity)
    monkeypatch.setattr(ban_executor, "upload_proof_media", _upload)
    monkeypatch.setattr(ban_executor, "demote_before_enforcement", _refusal)
    monkeypatch.setattr(ban_executor, "_execute_ban_record", _record)
    monkeypatch.setattr(moderation_enforcement, "deliver_queued_run", _none)
    monkeypatch.setattr(db.enforcement_ledger, "run_report", _report)
    monkeypatch.setattr(db.enforcement_ledger, "failed_report_targets", _failed_targets)
    monkeypatch.setattr(db.enforcement_ledger, "delivery_outcome", _outcome)
    monkeypatch.setattr(db.users_cache, "upsert_user", _none)
    monkeypatch.setattr(messages, "send_text", _none)

    await ban_executor.execute_ban(_Bot(), [], _meta())  # type: ignore[arg-type]

    failures = [entry for entry in log.errors if "left 1/2 group" in entry[0]]
    assert len(failures) == 1
    exc_info = failures[0][1].get("exc_info")
    assert isinstance(exc_info, BaseException)
    assert "CHAT_ADMIN_REQUIRED" in str(exc_info)
