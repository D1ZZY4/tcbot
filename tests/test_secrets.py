# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Inbound credential checks reject every malformed secret without raising."""

from __future__ import annotations

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
