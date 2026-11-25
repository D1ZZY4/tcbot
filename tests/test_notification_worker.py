# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""The review-card outbox retries transient edits and closes dead cards."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from pyrogram.types import InlineKeyboardMarkup

from tcbot import database as db
from tcbot import notification_worker
from tcbot.modules.helper.pipelines.errors.exceptions import BadRequest, FloodWait
from tcbot.utils import circuit_breaker as _cb
from tcbot.utils.time_and_date import monotonic


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
        "next_retry_at": "claimed-deadline",
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


def test_an_open_circuit_claims_no_card(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An OPEN circuit must not spend an attempt on an undelivered edit."""

    async def _no_claim(*_args: Any, **_kwargs: Any) -> list[dict[str, object]]:
        raise AssertionError("no card may be claimed while the circuit is open")

    monkeypatch.setattr(db.notifications_db, "claim_due_tasks", _no_claim)
    bot = _Bot()
    _cb.telegram.reset()
    _cb.telegram._state = _cb.CircuitState.OPEN
    # * A freshly opened circuit must not age into HALF_OPEN during the tick.
    _cb.telegram._opened_at = monotonic()
    try:
        asyncio.run(notification_worker.run_once(bot))  # type: ignore[arg-type]
    finally:
        _cb.telegram.reset()

    assert bot.edits == []


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


def test_a_held_probe_claims_no_card_and_spends_no_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Probe contention must not consume the retry budget of a decided card."""
    claimed: list[int] = []
    completed: list[dict[str, Any]] = []
    task = {**_task(), "attempts": notification_worker._MAX_ATTEMPTS}
    _wire(monkeypatch)

    async def _claim(limit: int = 10, *, retry_after: Any) -> list[dict[str, object]]:
        claimed.append(limit)
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
        assert _cb.telegram._half_open_probe_in_flight is True
    finally:
        _cb.telegram.reset()

    assert claimed == []
    assert completed == []
    assert bot.edits == []


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


def test_cancelling_an_edit_returns_the_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A shutdown before the edit settles must not spend the card's attempt."""
    released: list[dict[str, Any]] = []
    _wire(monkeypatch)

    async def _release(task_id: int, **kwargs: Any) -> None:
        released.append({"task_id": task_id, **kwargs})

    monkeypatch.setattr(db.notifications_db, "release_claim", _release)
    bot = _Bot(asyncio.CancelledError())

    _cb.telegram.reset()
    try:
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(notification_worker.run_once(bot))  # type: ignore[arg-type]
    finally:
        _cb.telegram.reset()

    assert released == [
        {
            "task_id": 1,
            "expected_attempts": 1,
            "expected_message_id": 900,
            "expected_next_retry_at": "claimed-deadline",
        }
    ]


def test_an_unadmitted_claim_gives_back_its_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A circuit refusal after the claim must not spend the card's budget."""
    released: list[dict[str, Any]] = []
    _wire(monkeypatch)
    bot = _Bot()

    async def _claim_then_open(
        limit: int = 10, *, retry_after: Any
    ) -> list[dict[str, object]]:
        # * Other Telegram traffic can trip the circuit after the claim but
        # * before this worker reaches its admission check.
        _cb.telegram._state = _cb.CircuitState.OPEN
        return [_task()]

    async def _release(task_id: int, **kwargs: Any) -> None:
        released.append({"task_id": task_id, **kwargs})

    monkeypatch.setattr(db.notifications_db, "claim_due_tasks", _claim_then_open)
    monkeypatch.setattr(db.notifications_db, "release_claim", _release)

    _cb.telegram.reset()
    try:
        asyncio.run(notification_worker.run_once(bot))  # type: ignore[arg-type]
    finally:
        _cb.telegram.reset()

    assert bot.edits == []
    assert released == [
        {
            "task_id": 1,
            "expected_attempts": 1,
            "expected_message_id": 900,
            "expected_next_retry_at": "claimed-deadline",
        }
    ]


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


def test_a_failed_sent_settlement_does_not_record_a_failed_card(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A landed edit must not be reported as failed when only its write fails."""
    completed: list[dict[str, Any]] = []
    task = {**_task(), "attempts": notification_worker._MAX_ATTEMPTS}
    _wire(monkeypatch)

    async def _claim(limit: int = 10, *, retry_after: Any) -> list[dict[str, object]]:
        return [task]

    async def _complete(task_id: int, **kwargs: Any) -> None:
        completed.append({"task_id": task_id, **kwargs})
        if kwargs.get("state") == "sent":
            raise RuntimeError("database unavailable")

    monkeypatch.setattr(db.notifications_db, "claim_due_tasks", _claim)
    monkeypatch.setattr(db.notifications_db, "complete_task", _complete)

    bot = _Bot()

    asyncio.run(notification_worker.run_once(bot))  # type: ignore[arg-type]

    assert len(bot.edits) == 1
    assert [entry["state"] for entry in completed] == ["sent"]


def test_a_not_modified_settlement_failure_does_not_mark_a_closed_card_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A card Telegram confirms as current must not be settled as failed."""
    completed: list[dict[str, Any]] = []
    task = {**_task(), "attempts": notification_worker._MAX_ATTEMPTS}
    _wire(monkeypatch)

    async def _claim(limit: int = 10, *, retry_after: Any) -> list[dict[str, object]]:
        return [task]

    async def _complete(task_id: int, **kwargs: Any) -> None:
        completed.append({"task_id": task_id, **kwargs})
        if kwargs.get("state") == "sent":
            raise RuntimeError("database unavailable")

    monkeypatch.setattr(db.notifications_db, "claim_due_tasks", _claim)
    monkeypatch.setattr(db.notifications_db, "complete_task", _complete)

    bot = _Bot(BadRequest("Message is not modified"))

    asyncio.run(notification_worker.run_once(bot))  # type: ignore[arg-type]

    assert len(bot.edits) == 1
    assert [entry["state"] for entry in completed] == ["sent"]


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
