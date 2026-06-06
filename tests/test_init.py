# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Studio

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


# ─────────────────── Configs dataclass properties ───────────────── #


def _make_configs(**overrides):
    from tcbot import Configs

    defaults = dict(
        bot_token="123:abc",
        owner_id=1,
        mongodb_uri="mongodb://localhost",
        db_name="tcbot",
        community_name="Test",
        prefixes=["/"],
        port="8080",
        main_group="-100100",
        main_channel="-100200",
        proofs="-100300/5",
        logs="-100400",
        logs_errors="-100500/7",
        appeals="-100600",
        appeal_log_handle="@test",
        proof_timeout_seconds=100,
        appeal_timeout_seconds=600,
        appeal_discussion_topic=3,
        extend_group="-100700",
        album_debounce_seconds=2,
        log_level=20,
        modules_load=[],
        modules_no_load=[],
    )
    defaults.update(overrides)
    return Configs(**defaults)


def test_configs_port_int_valid() -> None:
    assert _make_configs(port="9000").port_int == 9000


def test_configs_port_int_invalid_falls_back() -> None:
    assert _make_configs(port="notaport").port_int == 5000


def test_configs_main_group_id_set() -> None:
    assert _make_configs(main_group="-100999").main_group_id == -100999


def test_configs_main_group_id_empty() -> None:
    assert _make_configs(main_group="").main_group_id == 0


def test_configs_main_channel_id_set() -> None:
    assert _make_configs(main_channel="-100888").main_channel_id == -100888


def test_configs_main_channel_id_empty() -> None:
    assert _make_configs(main_channel="").main_channel_id == 0


def test_configs_extend_group_id_set() -> None:
    assert _make_configs(extend_group="-100777").extend_group_id == -100777


def test_configs_extend_group_id_empty() -> None:
    assert _make_configs(extend_group="").extend_group_id == 0


def test_configs_logs_tuple_plain() -> None:
    chat_id, thread_id = _make_configs(logs="-100400").logs_tuple
    assert chat_id == -100400
    assert thread_id is None


def test_configs_proofs_id_with_thread() -> None:
    chat_id, thread_id = _make_configs(proofs="-100300/5").proofs_id
    assert chat_id == -100300
    assert thread_id == 5


def test_configs_logs_errors_id_with_thread() -> None:
    chat_id, thread_id = _make_configs(logs_errors="-100500/7").logs_errors_id
    assert chat_id == -100500
    assert thread_id == 7


def test_configs_appeals_id_empty() -> None:
    chat_id, thread_id = _make_configs(appeals="").appeals_id
    assert chat_id == 0
    assert thread_id is None
