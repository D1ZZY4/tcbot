# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""MTProto base: unconfigured degrades to None, configured builds without connecting."""

from __future__ import annotations

import dataclasses

import pytest

from tcbot.database import mtproto


def _with_creds(monkeypatch: pytest.MonkeyPatch, api_id: int, api_hash: str) -> None:
    monkeypatch.setattr(mtproto, "_client", None)
    monkeypatch.setattr(
        mtproto.cfg,
        "_c",
        dataclasses.replace(mtproto.cfg._c, api_id=api_id, api_hash=api_hash),
    )


def test_unconfigured_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    _with_creds(monkeypatch, 0, "")

    assert mtproto.is_configured() is False
    assert mtproto.client() is None


def test_configured_builds_singleton_without_connecting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _with_creds(monkeypatch, 12345, "hash")

    first = mtproto.client()

    assert first is not None
    assert mtproto.client() is first
