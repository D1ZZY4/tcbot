# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Error classification: circuit labels and hints distinguish the service."""

from __future__ import annotations

import telegram.error as te
from pyrogram.errors import AuthKeyDuplicated
from pyrogram.session.session import AuthKeyNotFound
from sqlalchemy.exc import OperationalError

from tcbot import error_reporter as classify
from tcbot.utils.circuit_breaker import CircuitOpenError


def test_database_circuit_label() -> None:
    exc = CircuitOpenError("Circuit [postgres] is OPEN; call rejected.")
    assert classify._classify(exc) == "[~] PostgreSQL Circuit Open"


def test_telegram_circuit_label() -> None:
    exc = CircuitOpenError("Circuit [telegram] is OPEN; call rejected.")
    assert classify._classify(exc) == "[~] Circuit Open"


def test_database_label_case_insensitive() -> None:
    exc = CircuitOpenError("Circuit [PostgreSQL] is OPEN; call rejected.")
    assert classify._classify(exc) == "[~] PostgreSQL Circuit Open"


def test_dispatch_circuit_message_labels_telegram() -> None:
    # * The dispatch raise site spells the circuit inline without brackets.
    exc = CircuitOpenError("Telegram circuit is OPEN; call skipped.")
    assert classify._classify(exc) == "[~] Circuit Open"


def test_database_hint_distinct_and_ordered() -> None:
    database_hint = classify._action_hint("[~] PostgreSQL Circuit Open")
    telegram_hint = classify._action_hint("[~] Circuit Open")
    assert "PostgreSQL" in database_hint
    assert "Telegram" in telegram_hint
    assert database_hint != telegram_hint
    # * The database marker must sit ahead of the generic Circuit Open
    # * marker so the longer label matches the specific hint first.
    markers = [marker for marker, _ in classify._ACTION_HINTS]
    assert markers.index("PostgreSQL Circuit Open") < markers.index("Circuit Open")


def test_a_database_error_is_labelled_as_such() -> None:
    """A database failure carries the database label, not the code-bug label."""
    exc = OperationalError("SELECT 1", {}, Exception("connection refused"))
    assert classify._classify(exc) == "[DB] Database Error"


def test_benign_suppresses_connectivity_and_circuit() -> None:
    outage = OperationalError("SELECT 1", {}, Exception("connection refused"))
    assert classify._benign(outage) is True
    assert classify._benign(CircuitOpenError("Circuit [postgres] is OPEN")) is True
    assert classify._benign(CircuitOpenError("Circuit [telegram] is OPEN")) is True
    assert classify._benign(RuntimeError("bug")) is False


def test_owner_only_and_benign_filters_unchanged() -> None:
    assert classify._owner_only(te.Conflict("c")) is True
    assert classify._owner_only(OperationalError("s", {}, Exception("x"))) is False
    assert classify._benign(None) is False


def test_mtproto_auth_key_labels_operator_action() -> None:
    for exc in (AuthKeyNotFound("gone"), AuthKeyDuplicated("dup")):
        assert classify._classify(exc) == "[~] MTProto Auth Key Invalidated"
        assert "mtproto_state" in classify._action_hint(classify._classify(exc))
        assert classify._benign(exc) is False
