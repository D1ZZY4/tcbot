# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Error classification: circuit labels and hints distinguish the service."""

from __future__ import annotations

import telegram.error as te
from pymongo.errors import ConnectionFailure

from tcbot.utils.circuit_breaker import CircuitOpenError
from tcbot.utils.error_reporter import classify


def test_mongodb_circuit_label() -> None:
    exc = CircuitOpenError("Circuit [mongodb] is OPEN; call rejected.")
    assert classify._classify(exc) == "[~] MongoDB Circuit Open"


def test_telegram_circuit_label() -> None:
    exc = CircuitOpenError("Circuit [telegram] is OPEN; call rejected.")
    assert classify._classify(exc) == "[~] Circuit Open"


def test_mongodb_label_case_insensitive() -> None:
    exc = CircuitOpenError("Circuit [MongoDB] is OPEN; call rejected.")
    assert classify._classify(exc) == "[~] MongoDB Circuit Open"


def test_dispatch_circuit_message_labels_telegram() -> None:
    # * The dispatch raise site spells the circuit inline without brackets.
    exc = CircuitOpenError("Telegram circuit is OPEN; call skipped.")
    assert classify._classify(exc) == "[~] Circuit Open"


def test_mongodb_hint_distinct_and_ordered() -> None:
    mongo_hint = classify._action_hint("[~] MongoDB Circuit Open")
    telegram_hint = classify._action_hint("[~] Circuit Open")
    assert "Atlas" in mongo_hint
    assert "Telegram" in telegram_hint
    assert mongo_hint != telegram_hint
    # * The MongoDB marker must sit ahead of the generic Circuit Open marker
    # * so the longer label matches the specific hint first.
    markers = [marker for marker, _ in classify._ACTION_HINTS]
    assert markers.index("MongoDB Circuit Open") < markers.index("Circuit Open")


def test_benign_suppresses_connectivity_and_circuit() -> None:
    assert classify._benign(ConnectionFailure("no primary")) is True
    assert classify._benign(CircuitOpenError("Circuit [mongodb] is OPEN")) is True
    assert classify._benign(CircuitOpenError("Circuit [telegram] is OPEN")) is True
    assert classify._benign(RuntimeError("bug")) is False


def test_owner_only_and_benign_filters_unchanged() -> None:
    assert classify._owner_only(te.Conflict("c")) is True
    assert classify._owner_only(ConnectionFailure("x")) is False
    assert classify._benign(None) is False
