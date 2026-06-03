# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""Tests for tcbot.__init__ - config parsing helpers and Configs/cfg adapter."""

from __future__ import annotations

from tcbot import parse_chat_id, parse_list, parse_port

# ──────────────────────── parse_list ────────────────────────────── #


def test_parse_list_empty_string_returns_empty() -> None:
    assert parse_list("") == []


def test_parse_list_whitespace_only_returns_empty() -> None:
    assert parse_list("   ") == []


def test_parse_list_python_list_format() -> None:
    result = parse_list('["/", "!", "."]')
    assert result == ["/", "!", "."]


def test_parse_list_csv_fallback() -> None:
    result = parse_list("/, !, .")
    assert "/" in result
    assert "!" in result


def test_parse_list_single_item() -> None:
    result = parse_list("['/']")
    assert result == ["/"]


# ──────────────────────── parse_port ────────────────────────────── #


def test_parse_port_valid_integer() -> None:
    assert parse_port("8080") == 8080


def test_parse_port_empty_string_returns_5000() -> None:
    assert parse_port("") == 5000


def test_parse_port_auto_returns_5000() -> None:
    assert parse_port("auto") == 5000


def test_parse_port_AUTO_uppercase_returns_5000() -> None:
    assert parse_port("AUTO") == 5000


def test_parse_port_non_integer_returns_5000() -> None:
    assert parse_port("notanumber") == 5000


def test_parse_port_zero_returns_5000() -> None:
    assert parse_port("0") == 5000


def test_parse_port_negative_returns_5000() -> None:
    assert parse_port("-1") == 5000


def test_parse_port_above_65535_returns_5000() -> None:
    assert parse_port("99999") == 5000


def test_parse_port_boundary_1() -> None:
    assert parse_port("1") == 1


def test_parse_port_boundary_65535() -> None:
    assert parse_port("65535") == 65535


# ──────────────────────── parse_chat_id ─────────────────────────── #


def test_parse_chat_id_empty_returns_zero_none() -> None:
    assert parse_chat_id("") == (0, None)


def test_parse_chat_id_plain_chat_id() -> None:
    chat_id, thread_id = parse_chat_id("-1001234567890")
    assert chat_id == -1001234567890
    assert thread_id is None


def test_parse_chat_id_with_thread() -> None:
    chat_id, thread_id = parse_chat_id("-1001234567890/42")
    assert chat_id == -1001234567890
    assert thread_id == 42


def test_parse_chat_id_positive_id() -> None:
    chat_id, thread_id = parse_chat_id("123456")
    assert chat_id == 123456
    assert thread_id is None


def test_parse_chat_id_thread_zero() -> None:
    chat_id, thread_id = parse_chat_id("-100001/0")
    assert thread_id == 0


# ──────────────────── _CfgAdapter via cfg singleton ─────────────── #


def test_cfg_community_name_is_string() -> None:
    from tcbot import cfg

    assert isinstance(cfg.community_name, str)


def test_cfg_prefixes_is_list() -> None:
    from tcbot import cfg

    assert isinstance(cfg.prefixes, list)
    assert len(cfg.prefixes) > 0


def test_cfg_port_is_int() -> None:
    from tcbot import cfg

    assert isinstance(cfg.port, int)


def test_cfg_port_is_valid_range() -> None:
    from tcbot import cfg

    assert 1 <= cfg.port <= 65535


def test_cfg_db_name_is_non_empty_string() -> None:
    from tcbot import cfg

    assert isinstance(cfg.db_name, str)
    assert cfg.db_name.strip()


def test_cfg_logs_is_tuple() -> None:
    from tcbot import cfg

    result = cfg.logs
    assert isinstance(result, tuple)
    assert len(result) == 2


def test_cfg_proofs_is_tuple() -> None:
    from tcbot import cfg

    result = cfg.proofs
    assert isinstance(result, tuple)
    assert len(result) == 2


def test_cfg_modules_load_is_list() -> None:
    from tcbot import cfg

    assert isinstance(cfg.modules_load, list)


def test_cfg_modules_no_load_is_list() -> None:
    from tcbot import cfg

    assert isinstance(cfg.modules_no_load, list)


def test_cfg_album_debounce_positive() -> None:
    from tcbot import cfg

    assert cfg.album_debounce >= 1


def test_cfg_proof_timeout_positive() -> None:
    from tcbot import cfg

    assert cfg.proof_timeout >= 1


def test_cfg_appeal_timeout_positive() -> None:
    from tcbot import cfg

    assert cfg.appeal_timeout >= 1


def test_cfg_log_level_is_int() -> None:
    from tcbot import cfg

    assert isinstance(cfg.log_level, int)
