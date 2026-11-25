# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Kurigram dispatcher workers are sized without starving the database pool."""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

from tcbot.database import mtproto


def _cfg(workers: int, pool: int = 5, overflow: int = 5) -> SimpleNamespace:
    return SimpleNamespace(
        kurigram_workers=workers, db_pool_size=pool, db_max_overflow=overflow
    )


def test_automatic_workers_scale_with_cpu_and_pool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(mtproto, "cfg", _cfg(0))
    monkeypatch.setattr(os, "cpu_count", lambda: 4)

    assert mtproto._worker_count() == 16


def test_automatic_workers_never_exceed_the_application_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(mtproto, "cfg", _cfg(0, pool=64, overflow=64))
    monkeypatch.setattr(os, "cpu_count", lambda: 128)

    assert mtproto._worker_count() == 64


def test_an_explicit_worker_count_is_honoured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(mtproto, "cfg", _cfg(32))

    assert mtproto._worker_count() == 32
