# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""
Tests for config parsing helpers in tcbot.__init__.
"""

from __future__ import annotations

import pytest

from tcbot import Configs, parse_list


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
