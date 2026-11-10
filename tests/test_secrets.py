# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Inbound credential checks reject every malformed secret without raising."""

from __future__ import annotations

import pytest

import tcbot.alive as alive_mod
from tcbot.utils.secrets import secret_matches


def test_secret_matches_accepts_the_exact_secret() -> None:
    assert secret_matches("hook-secret", "hook-secret") is True


def test_secret_matches_rejects_a_different_secret() -> None:
    assert secret_matches("wrong", "hook-secret") is False


def test_secret_matches_rejects_a_non_ascii_credential_without_raising() -> None:
    # * hmac.compare_digest raises TypeError on non-ASCII strings, so the
    # * helper must compare bytes to keep a malformed header a rejection.
    assert secret_matches("hook-sécret", "hook-secret") is False
    assert secret_matches("hook-sécret", "hook-sécret") is True


def test_secret_matches_rejects_an_empty_credential() -> None:
    assert secret_matches("", "hook-secret") is False


def test_webhook_403_when_the_secret_header_is_not_ascii(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A non-ASCII secret header is a rejected request, not a server error."""
    monkeypatch.setattr(alive_mod, "_wh_secret", "hook-secret")
    monkeypatch.setattr(alive_mod, "_wh_queue", object())
    monkeypatch.setattr(alive_mod, "_wh_loop", object())
    monkeypatch.setattr(alive_mod, "_wh_bot", object())
    headers = {"X-Telegram-Bot-Api-Secret-Token": "hook-sécret"}
    with alive_mod._app.test_request_context(
        "/webhook", method="POST", headers=headers, json={"update_id": 1}
    ):
        body, code = alive_mod.webhook_route()
    assert code == 403
    assert body == "Forbidden"
