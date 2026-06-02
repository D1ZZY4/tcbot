# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""Tests for config parsing helpers in tcbot.__init__."""

from __future__ import annotations

import logging

import pytest

from tcbot import Configs, _warn_bot_token_fmt, _warn_mongodb_uri_fmt, parse_list


def test_parse_list_accepts_python_list_literal() -> None:
    assert parse_list('["/", "!", "."]') == ["/", "!", "."]


def test_parse_list_falls_back_to_csv_strings() -> None:
    assert parse_list("/,!,.") == ["/", "!", "."]


@pytest.mark.parametrize("owner_id", [None, "", "0", "-1", "abc"])
def test_configs_load_rejects_invalid_owner_id(
    monkeypatch: pytest.MonkeyPatch, owner_id: str | None
) -> None:
    monkeypatch.setattr("tcbot.find_dotenv", lambda *args, **kwargs: "")
    monkeypatch.setattr("tcbot.load_dotenv", lambda *args, **kwargs: None)
    monkeypatch.setenv("BOT_TOKEN", "test:token")
    if owner_id is None:
        monkeypatch.delenv("OWNER_ID", raising=False)
    else:
        monkeypatch.setenv("OWNER_ID", owner_id)

    with pytest.raises(RuntimeError, match="OWNER_ID"):
        Configs.load()


def test_configs_load_reads_custom_appeal_log_handle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("tcbot.find_dotenv", lambda *args, **kwargs: "")
    monkeypatch.setattr("tcbot.load_dotenv", lambda *args, **kwargs: None)
    monkeypatch.setenv("BOT_TOKEN", "test:token")
    monkeypatch.setenv("OWNER_ID", "123456")
    monkeypatch.setenv("APPEAL_LOG_HANDLE", "@ExampleAppeals")

    cfg = Configs.load()

    assert cfg.appeal_log_handle == "@ExampleAppeals"


# ─────────────────── BOT_TOKEN format validator ─────────────────── #


@pytest.mark.parametrize(
    "token",
    [
        # Exactly 35 chars after the colon: uppercase A-Z (26) + lowercase a-i (9)
        "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi",
        "9876543210:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi",
    ],
)
def test_warn_bot_token_fmt_valid_no_warning(
    token: str, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger="tcbot"):
        _warn_bot_token_fmt(token)
    assert not any("BOT_TOKEN" in r.message for r in caplog.records)


@pytest.mark.parametrize(
    "token",
    [
        "not_a_real_token",
        "test:token",
        "",
        "12345:short",
        "nocodon",
    ],
)
def test_warn_bot_token_fmt_invalid_emits_warning(
    token: str, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger="tcbot"):
        _warn_bot_token_fmt(token)
    assert any("BOT_TOKEN" in r.message for r in caplog.records)


# ─────────────────── MONGODB_URI format validator ────────────────── #


@pytest.mark.parametrize(
    "uri",
    [
        "mongodb://localhost:27017/mydb",
        "mongodb+srv://user:pass@cluster.mongodb.net/mydb",
    ],
)
def test_warn_mongodb_uri_fmt_valid_no_warning(
    uri: str, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger="tcbot"):
        _warn_mongodb_uri_fmt(uri)
    assert not any("MONGODB_URI" in r.message for r in caplog.records)


@pytest.mark.parametrize(
    "uri",
    [
        "http://localhost/db",
        "postgres://localhost/db",
        "not-a-uri",
        "",
    ],
)
def test_warn_mongodb_uri_fmt_invalid_emits_warning(
    uri: str, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger="tcbot"):
        _warn_mongodb_uri_fmt(uri)
    assert any("MONGODB_URI" in r.message for r in caplog.records)
