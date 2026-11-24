# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""The review-card outbox retries transient edits and closes dead cards."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from pyrogram.errors import BadRequest, FloodWait
from pyrogram.types import InlineKeyboardMarkup

from tcbot import database as db
from tcbot import notification_worker
from tcbot.utils import circuit_breaker as _cb


class _Bot:
    def __init__(self, error: BaseException | None = None) -> None:
        self.error = error
        self.edits: list[dict[str, Any]] = []

    async def edit_message_text(
        self, chat_id: int, message_id: int, text: str | None = None, **kwargs: Any
    ) -> None:
        self.edits.append({"text": text, "kwargs": kwargs})
        if self.error is not None:
            raise self.error


def _task() -> dict[str, object]:
    return {
        "id": 1,
        "action_id": 2,
        "chat_id": -1001,
        "message_id": 900,
        "attempts": 1,
    }


def _wire(
    monkeypatch: pytest.MonkeyPatch,
    *,
    action_status: str = "revoked",
    has_pending_appeal: bool = False,
    review_message_id: int | None = None,
) -> list[dict[str, Any]]:
    completed: list[dict[str, Any]] = []

    async def _claim(limit: int = 10, *, retry_after: Any) -> list[dict[str, object]]:
        return [_task()]

    async def _load(task_id: int) -> dict[str, object]:
        return {
            "external_ref": "ref",
            "target_user_id": 42,
            "status": action_status,
            "has_pending_appeal": has_pending_appeal,
            "review_message_id": (
                str(review_message_id) if review_message_id is not None else None
            ),
        }

    async def _locale(chat_id: int) -> str:
        return "en-US"

    async def _complete(task_id: int, **kwargs: Any) -> None:
        completed.append({"task_id": task_id, **kwargs})

    monkeypatch.setattr(db.notifications_db, "claim_due_tasks", _claim)
    monkeypatch.setattr(db.notifications_db, "load_task_action", _load)
    monkeypatch.setattr(notification_worker, "_group_locale", _locale)
    monkeypatch.setattr(db.notifications_db, "complete_task", _complete)
    return completed


def test_a_failed_card_edit_is_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    completed = _wire(monkeypatch)
    bot = _Bot(RuntimeError("telegram down"))

    asyncio.run(notification_worker.run_once(bot))  # type: ignore[arg-type]

    assert len(bot.edits) == 1
    assert completed[0]["state"] == "pending"
    assert completed[0]["retry_after"] is not None


def test_a_rate_limit_reply_does_not_trip_the_shared_circuit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A Telegram service answer must not count as a transport failure."""
    completed = _wire(monkeypatch)
    bot = _Bot(FloodWait(1))

    _cb.telegram.reset()
    try:
        asyncio.run(notification_worker.run_once(bot))  # type: ignore[arg-type]
        assert _cb.telegram.state is _cb.CircuitState.CLOSED
    finally:
        _cb.telegram.reset()

    assert len(bot.edits) == 1
    assert completed[0]["state"] == "pending"


def test_a_half_open_circuit_claims_one_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    claimed: list[int] = []

    async def _claim(limit: int = 10, *, retry_after: Any) -> list[dict[str, object]]:
        claimed.append(limit)
        return [_task()]

    _wire(monkeypatch)
    monkeypatch.setattr(db.notifications_db, "claim_due_tasks", _claim)

    _cb.telegram.reset()
    _cb.telegram._state = _cb.CircuitState.HALF_OPEN
    try:
        asyncio.run(notification_worker.run_once(_Bot()))  # type: ignore[arg-type]
    finally:
        _cb.telegram.reset()

    assert claimed == [1]


def test_a_reserved_half_open_probe_is_not_bypassed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A second worker must not edit a card while another probe is in flight."""
    _wire(monkeypatch)
    bot = _Bot()

    _cb.telegram.reset()
    _cb.telegram._state = _cb.CircuitState.HALF_OPEN
    try:
        assert _cb.telegram.try_acquire() is True
        asyncio.run(notification_worker.run_once(bot))  # type: ignore[arg-type]
    finally:
        _cb.telegram.reset()

    assert bot.edits == []


def test_a_never_admitted_task_becomes_terminal_at_the_ceiling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A flapping breaker must not leave a maxed-out row pending forever."""
    completed: list[dict[str, Any]] = []
    task = {**_task(), "attempts": notification_worker._MAX_ATTEMPTS}
    _wire(monkeypatch)

    async def _claim(limit: int = 10, *, retry_after: Any) -> list[dict[str, object]]:
        return [task]

    async def _complete(task_id: int, **kwargs: Any) -> None:
        completed.append({"task_id": task_id, **kwargs})

    monkeypatch.setattr(db.notifications_db, "claim_due_tasks", _claim)
    monkeypatch.setattr(db.notifications_db, "complete_task", _complete)
    bot = _Bot()

    _cb.telegram.reset()
    _cb.telegram._state = _cb.CircuitState.HALF_OPEN
    try:
        assert _cb.telegram.try_acquire() is True
        asyncio.run(notification_worker.run_once(bot))  # type: ignore[arg-type]
    finally:
        _cb.telegram.reset()

    assert bot.edits == []
    assert completed[0]["state"] == "failed"
    assert "circuit" in completed[0]["error"].lower()


def test_cancelling_a_card_edit_releases_the_half_open_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Shutdown during the recovery probe must not strand the breaker."""
    _wire(monkeypatch)
    bot = _Bot(asyncio.CancelledError())

    _cb.telegram.reset()
    _cb.telegram._state = _cb.CircuitState.HALF_OPEN
    try:
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(notification_worker.run_once(bot))  # type: ignore[arg-type]
        assert _cb.telegram._half_open_probe_in_flight is False
    finally:
        _cb.telegram.reset()


def test_a_worker_error_at_the_attempt_ceiling_is_terminal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A task that fails before the retry decision must not retry forever."""
    completed: list[dict[str, Any]] = []
    task = {**_task(), "attempts": notification_worker._MAX_ATTEMPTS}

    async def _claim(limit: int = 10, *, retry_after: Any) -> list[dict[str, object]]:
        return [task]

    async def _load(task_id: int) -> dict[str, object]:
        raise RuntimeError("database unavailable")

    async def _complete(task_id: int, **kwargs: Any) -> None:
        completed.append({"task_id": task_id, **kwargs})

    monkeypatch.setattr(db.notifications_db, "claim_due_tasks", _claim)
    monkeypatch.setattr(db.notifications_db, "load_task_action", _load)
    monkeypatch.setattr(db.notifications_db, "complete_task", _complete)

    asyncio.run(notification_worker.run_once(_Bot()))  # type: ignore[arg-type]

    assert completed[0]["state"] == "failed"


def test_a_deleted_card_is_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    completed = _wire(monkeypatch)
    bot = _Bot(BadRequest("Message to edit not found"))

    asyncio.run(notification_worker.run_once(bot))  # type: ignore[arg-type]

    assert completed[0]["state"] == "skipped"


def test_a_live_review_leaves_the_card_alone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    completed = _wire(
        monkeypatch,
        action_status="active",
        has_pending_appeal=True,
        review_message_id=900,
    )
    bot = _Bot()

    asyncio.run(notification_worker.run_once(bot))  # type: ignore[arg-type]

    assert bot.edits == []
    assert completed[0]["state"] == "skipped"


def test_a_rejected_appeal_closes_its_still_active_ban_card(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A rejected appeal keeps the ban active but the card is settled."""
    completed = _wire(monkeypatch, action_status="active", has_pending_appeal=False)
    bot = _Bot()

    asyncio.run(notification_worker.run_once(bot))  # type: ignore[arg-type]

    assert len(bot.edits) == 1
    markup = bot.edits[0]["kwargs"]["reply_markup"]
    assert isinstance(markup, InlineKeyboardMarkup)
    assert not markup.inline_keyboard
    assert completed[0]["state"] == "sent"


def test_an_invalid_task_is_settled_instead_of_retried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A row that can never succeed must stop consuming a worker slot.

    A missing message id makes the edit impossible. Leaving the row
    pending lets the claim advance its attempt count every tick forever.
    """
    completed: list[dict[str, Any]] = []
    task = {**_task(), "message_id": 0}

    async def _claim(limit: int = 10, *, retry_after: Any) -> list[dict[str, object]]:
        return [task]

    async def _complete(task_id: int, **kwargs: Any) -> None:
        completed.append({"task_id": task_id, **kwargs})

    monkeypatch.setattr(db.notifications_db, "claim_due_tasks", _claim)
    monkeypatch.setattr(db.notifications_db, "complete_task", _complete)

    asyncio.run(notification_worker.run_once(_Bot()))  # type: ignore[arg-type]

    assert completed[0]["state"] == "failed"
