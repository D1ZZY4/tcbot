# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Demote notify levels: benign DM failures stay quiet, log gaps stay loud."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

import pytest
from telegram.error import BadRequest, Forbidden

from tcbot.modules.helper.workflows.demote_flow import Demote

if TYPE_CHECKING:
    from collections.abc import Iterator

_LOG_NAME = "tcbot.modules.helper.workflows.demote_flow"


class _FakeBot:
    """Bot double failing each send_message with the next queued outcome."""

    def __init__(self, outcomes: list[Any]) -> None:
        self._outcomes = outcomes

    async def send_message(self, *args: Any, **kwargs: Any) -> Any:
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


@pytest.fixture
def _demote_no_db(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Stub the role removal so no database is touched."""

    async def _removed(target_id: int, target_role: str) -> bool:
        return True

    monkeypatch.setattr(Demote, "remove_role", _removed)
    yield


def _run(
    bot: _FakeBot,
    caplog: pytest.LogCaptureFixture,
) -> bool:
    with caplog.at_level(logging.DEBUG, logger=_LOG_NAME):
        return asyncio.run(
            Demote.execute(bot, 7937858374, "Target", "admin", 1, "Exec")  # type: ignore[arg-type]
        )


def _error_records(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        r.getMessage()
        for r in caplog.records
        if r.name == _LOG_NAME and r.levelno >= logging.ERROR
    ]


def test_blocked_dm_stays_quiet(
    _demote_no_db: None, caplog: pytest.LogCaptureFixture
) -> None:
    assert _run(_FakeBot([{"id": 1}, Forbidden("bot was blocked")]), caplog) is True
    assert _error_records(caplog) == []


def test_chat_not_found_dm_stays_quiet(
    _demote_no_db: None, caplog: pytest.LogCaptureFixture
) -> None:
    assert _run(_FakeBot([{"id": 1}, BadRequest("Chat not found")]), caplog) is True
    assert _error_records(caplog) == []


def test_unexpected_dm_failure_warns_only(
    _demote_no_db: None, caplog: pytest.LogCaptureFixture
) -> None:
    assert _run(_FakeBot([{"id": 1}, RuntimeError("boom")]), caplog) is True
    assert _error_records(caplog) == []
    assert any(
        r.levelno == logging.WARNING and "Demote DM send failed" in r.getMessage()
        for r in caplog.records
        if r.name == _LOG_NAME
    )


def test_log_send_failure_still_loud(
    _demote_no_db: None, caplog: pytest.LogCaptureFixture
) -> None:
    assert _run(_FakeBot([RuntimeError("boom"), {"id": 2}]), caplog) is True
    assert any("Demote log send failed" in msg for msg in _error_records(caplog))
