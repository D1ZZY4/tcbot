# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Error fingerprints: recurring background failures dedupe instead of flooding."""

from __future__ import annotations

import logging

from tcbot.utils import error_reporter


def _record(message: str) -> logging.LogRecord:
    return logging.LogRecord("t", logging.ERROR, __file__, 1, message, None, None)


def test_normalize_strips_task_ids_and_addresses() -> None:
    assert (
        error_reporter._normalize_fp_text("Task exception | Task-7891 at 0x7f8b1c2d")
        == "Task exception | Task-# at 0x#"
    )


def test_recurring_loop_failures_share_fingerprint() -> None:
    first = error_reporter._fingerprint_record(
        _record("Task exception was never retrieved | Task: Task-7891 done")
    )
    second = error_reporter._fingerprint_record(
        _record("Task exception was never retrieved | Task: Task-8010 done")
    )
    assert first == second


def test_distinct_errors_keep_distinct_fingerprints() -> None:
    assert error_reporter._fingerprint_exc(
        RuntimeError("boom-a")
    ) != error_reporter._fingerprint_exc(RuntimeError("boom-b"))
