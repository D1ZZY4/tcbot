# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Error classification: circuit labels and hints distinguish the service."""

from __future__ import annotations

import logging

from pyrogram.errors import AuthKeyDuplicated, RPCError
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


class TimedOut(RPCError):
    """Stand-in for Kurigram's RPC timeout, matched by name and base type."""


def test_builtin_timeout_is_not_labelled_as_a_telegram_failure() -> None:
    """A database or worker deadline must point at the deadline, not Telegram."""
    exc = TimeoutError("database call timed out")
    label = classify._classify(exc)
    assert label == "[~] Async Timeout"
    assert "deadline" in classify._action_hint(label).lower()
    assert "Telegram" not in label


def test_rpc_timeout_keeps_the_telegram_label() -> None:
    assert (
        classify._classify(TimedOut("rpc call timed out")) == "[~] Telegram Timed Out"
    )


def test_benign_suppresses_connectivity_and_circuit() -> None:
    outage = OperationalError("SELECT 1", {}, Exception("connection refused"))
    assert classify._benign(outage) is True
    assert classify._benign(CircuitOpenError("Circuit [postgres] is OPEN")) is True
    assert classify._benign(CircuitOpenError("Circuit [telegram] is OPEN")) is True
    assert classify._benign(RuntimeError("bug")) is False


def test_owner_only_and_benign_filters_unchanged() -> None:
    assert classify._owner_only(classify.PollingConflictError("c")) is True
    assert classify._owner_only(OperationalError("s", {}, Exception("x"))) is False
    assert classify._benign(None) is False


def test_mtproto_auth_key_labels_operator_action() -> None:
    for exc in (AuthKeyNotFound("gone"), AuthKeyDuplicated("dup")):
        assert classify._classify(exc) == "[~] MTProto Auth Key Invalidated"
        assert "mtproto_state" in classify._action_hint(classify._classify(exc))
        assert classify._benign(exc) is False


class SessionRevoked(Exception):
    """Stand-in for the Kurigram exception, matched by type name."""


def test_revoked_session_is_an_auth_failure_not_a_code_bug() -> None:
    exc = SessionRevoked("session revoked")
    assert classify._classify(exc) == "[~] MTProto Auth Key Invalidated"
    assert "mtproto_state" in classify._action_hint(classify._classify(exc))


class _CatalogError(Exception):
    sqlstate = "3D000"


def test_invalid_catalog_is_reported_not_suppressed_as_an_outage() -> None:
    exc = OperationalError("SELECT 1", {}, _CatalogError("database does not exist"))
    assert classify._benign(exc) is False
    assert classify._classify(exc) == "[DB] Database Error"


def _record(message: str) -> logging.LogRecord:
    return logging.LogRecord(
        "tcbot.test", logging.ERROR, "test.py", 1, message, (), None
    )


def test_log_noise_only_matches_the_execution_tracer() -> None:
    assert classify._log_noise(_record("[cmd_x] uid=1 raised after 12.3ms")) is True
    assert classify._log_noise(_record("Worker raised after 12.3ms")) is False
    assert classify._log_noise(_record("[cmd_x] uid=1 ok (12.3ms)")) is False
