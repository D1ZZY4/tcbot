# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Redis client liveness: mark_op feeds liveness() and logs the failure once."""

from __future__ import annotations

import pytest

import tcbot.database.redis_client as redis_client_mod


@pytest.fixture(autouse=True)
def _reset_liveness(monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolate module liveness between tests."""
    monkeypatch.setattr(redis_client_mod, "_liveness", None)


def test_mark_op_tracks_liveness_through_failures_and_recovery() -> None:
    redis_client_mod.mark_op(ok=True)
    assert redis_client_mod.liveness() is True
    redis_client_mod.mark_op(ok=False)
    assert redis_client_mod.liveness() is False
    redis_client_mod.mark_op(ok=True)
    assert redis_client_mod.liveness() is True


def test_mark_op_logs_transition_once(monkeypatch: pytest.MonkeyPatch) -> None:
    warnings: list[str] = []
    monkeypatch.setattr(
        redis_client_mod.log, "warning", lambda msg: warnings.append(msg)
    )
    redis_client_mod.mark_op(ok=False)
    redis_client_mod.mark_op(ok=False)
    assert len(warnings) == 1
