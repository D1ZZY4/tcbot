# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Runtime configuration parsing and the primary-group contract."""

from __future__ import annotations

import dataclasses

import pytest

from tcbot import (
    DB_SCHEMAS,
    Configs,
    _db_schema_from_env,
    cfg,
    parse_chat_id,
    parse_list,
    parse_port,
)


def _load(monkeypatch: pytest.MonkeyPatch, **env: str) -> Configs:
    """Load a fresh Configs with *env* applied over the required defaults."""
    base: dict[str, str] = {
        "BOT_TOKEN": "000000:dummy-token-for-lint000000000000000",
        "DATABASE_URL": "postgresql://localhost:5432/tcbot",
        "OWNER_ID": "1",
        "PROOFS": "-1000000000001",
    }
    base.update(env)
    for key in (
        "MAIN_GROUP",
        "MAIN_CHANNEL",
        "LOGS",
        "LOGS_ERRORS",
        "APPEALS",
        "PORT",
        "BIND_HOST",
        "PG_CRON_ENABLED",
        "PREFIXES",
        "REDIS_URL",
        "COMMUNITY_NAME",
        "MTPROTO_SESSION",
        "SENTRY_DSN",
        "API_ID",
        "API_HASH",
        "LOG_LEVEL",
    ):
        monkeypatch.delenv(key, raising=False)
    for key, value in base.items():
        monkeypatch.setenv(key, value)
    return Configs.load(env_file="does-not-exist.env")


@pytest.mark.parametrize("schema", sorted(DB_SCHEMAS))
def test_owned_schemas_are_accepted(
    monkeypatch: pytest.MonkeyPatch, schema: str
) -> None:
    monkeypatch.setenv("DB_SCHEMA", schema)
    assert _db_schema_from_env() == schema


def test_an_unknown_schema_falls_back_to_public(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A misspelled schema must never create a fourth schema at startup."""
    monkeypatch.setenv("DB_SCHEMA", "publik")
    assert _db_schema_from_env() == "public"


def test_is_primary_group_matches_negative_group_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Telegram group ids are negative; the primary group must still match."""
    loaded = _load(monkeypatch, MAIN_GROUP="-1003872207988")
    assert loaded.main_group == -1003872207988
    assert loaded.is_primary_group(-1003872207988) is True
    assert loaded.is_primary_group(-1009999999999) is False


def test_is_primary_group_rejects_unset_sentinel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``0`` means unconfigured; it must never match a real chat."""
    loaded = _load(monkeypatch)
    assert loaded.main_group == 0
    assert loaded.is_primary_group(0) is False
    assert loaded.is_primary_group(-1001234567890) is False
    assert loaded.is_primary_group(None) is False


def test_is_primary_group_requires_configured_main_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A configured chat never matches when MAIN_GROUP is unset."""
    loaded = _load(monkeypatch)
    assert loaded.is_primary_group(-1001234567890) is False


def test_positive_main_group_is_treated_as_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A user id is not a group: a positive MAIN_GROUP must never match."""
    loaded = _load(monkeypatch, MAIN_GROUP="123456789")
    assert loaded.main_group == 0
    assert loaded.is_primary_group(123456789) is False


def test_chat_destinations_parse_into_chat_thread_pairs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Log, proof, error, and appeal destinations resolve to (chat, thread)."""
    loaded = _load(
        monkeypatch,
        LOGS="-1001111111111/7",
        LOGS_ERRORS="-1002222222222",
        APPEALS="-1003333333333/9",
        PROOFS="-1004444444444",
    )
    assert loaded.logs == (-1001111111111, 7)
    assert loaded.logs_errors == (-1002222222222, None)
    assert loaded.appeals == (-1003333333333, 9)
    assert loaded.proofs == (-1004444444444, None)


def test_proofs_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    """A ban needs an evidence destination, so boot refuses an empty value."""
    with pytest.raises(RuntimeError, match="PROOFS is required"):
        _load(monkeypatch, PROOFS="  ")
    with pytest.raises(RuntimeError, match="PROOFS is required"):
        _load(monkeypatch, PROOFS="not-a-chat")
    # * A positive id names a user, not a chat that can hold evidence.
    with pytest.raises(RuntimeError, match="PROOFS is required"):
        _load(monkeypatch, PROOFS="123456789")


def test_invalid_chat_id_falls_back_to_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A malformed destination resolves to the unset sentinel, not a crash."""
    loaded = _load(monkeypatch, LOGS="not-a-chat")
    assert loaded.logs == (0, None)


def test_non_positive_thread_id_is_dropped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Telegram rejects thread id 0, so the destination keeps its chat only."""
    loaded = _load(monkeypatch, LOGS="-1001111111111/0")
    assert loaded.logs == (-1001111111111, None)


@pytest.mark.parametrize("raw", ["-1001111111111/abc", "-1001111111111/42/99"])
def test_malformed_thread_keeps_the_chat(
    monkeypatch: pytest.MonkeyPatch, raw: str
) -> None:
    """A bad thread segment must not disable an otherwise valid chat ID."""
    loaded = _load(monkeypatch, LOGS=raw)
    assert loaded.logs == (-1001111111111, None)


def test_port_falls_back_to_default_for_invalid_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unusable PORT never reaches the keep-alive server."""
    assert _load(monkeypatch, PORT="auto").port == 5000
    assert _load(monkeypatch, PORT="70000").port == 5000
    assert _load(monkeypatch, PORT="not-a-port").port == 5000
    assert _load(monkeypatch, PORT="8080").port == 8080


def test_prefixes_are_immutable_and_defaulted(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prefix lists are tuples, so no caller can mutate the shared config."""
    loaded = _load(monkeypatch)
    assert loaded.prefixes == ("/", "!", ".")
    assert _load(monkeypatch, PREFIXES="['!', '?']").prefixes == ("!", "?")


def test_config_is_frozen(monkeypatch: pytest.MonkeyPatch) -> None:
    """The runtime config cannot be mutated after load."""
    loaded = _load(monkeypatch)
    with pytest.raises(dataclasses.FrozenInstanceError):
        loaded.port = 1234  # type: ignore[misc]


def test_dataclasses_replace_keeps_a_usable_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tests rebuild a config through dataclasses.replace without losing fields."""
    loaded = _load(monkeypatch, MAIN_GROUP="-1001234567890")
    patched = dataclasses.replace(loaded, main_group=-1009999999999)
    assert patched.main_group == -1009999999999
    assert patched.bot_token == loaded.bot_token
    assert patched.is_primary_group(-1009999999999) is True


def test_module_level_cfg_exposes_the_parsed_config() -> None:
    """The shared singleton is the parsed Configs instance."""
    assert isinstance(cfg, Configs)
    assert cfg.bot_token
    assert cfg.initial_owner_id > 0
    assert cfg.mtproto_enabled == (cfg.api_id > 0 and bool(cfg.api_hash))


def test_parse_helpers_keep_their_contract() -> None:
    """The exported parsing helpers keep their documented behaviour."""
    assert parse_list("") == []
    assert parse_list("['a', 'b']") == ["a", "b"]
    assert parse_list("a, b") == ["a", "b"]
    assert parse_port("") == 5000
    assert parse_chat_id("") == (0, None)


def test_parse_list_drops_blank_entries_in_both_forms() -> None:
    """A literal list and CSV form of the same list produce equal output.

    MODULES_LOAD treats an empty string as an invalid module name, so blank
    entries must be discarded however the operator wrote the variable.
    """
    assert parse_list("['bans', '', '  ']") == ["bans"]
    assert parse_list("bans,,") == ["bans"]
    assert parse_list("[1, None, 'bans']") == ["1", "None", "bans"]


def test_env_fallbacks_use_documented_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Blank optional variables fall back to their documented defaults."""
    loaded = _load(monkeypatch, COMMUNITY_NAME="  ")
    assert loaded.community_name == "Bot"
    assert loaded.main_channel == 0


def test_main_channel_accepts_a_channel_and_rejects_a_user_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A negative id is a channel; a positive id names a user and is unset."""
    assert (
        _load(monkeypatch, MAIN_CHANNEL="-1001234567890").main_channel == -1001234567890
    )
    assert _load(monkeypatch, MAIN_CHANNEL="123456789").main_channel == 0


def test_infrastructure_chats_are_recognised_without_forum_threads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every deployment destination is infrastructure, including thread forms."""
    loaded = _load(
        monkeypatch,
        MAIN_CHANNEL="-1001",
        MAIN_GROUP="-1002",
        PROOFS="-1003",
        LOGS="-1004/7",
        LOGS_ERRORS="-1005",
        APPEALS="-1006",
    )
    for chat_id in (-1001, -1002, -1003, -1004, -1005, -1006):
        assert loaded.is_infrastructure_chat(chat_id) is True
    assert loaded.is_infrastructure_chat(-9999) is False
    assert loaded.is_infrastructure_chat(None) is False


def test_optional_secrets_stay_empty_when_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unset optional credentials stay empty instead of becoming truthy."""
    loaded = _load(monkeypatch)
    assert loaded.redis_url is None
    assert loaded.sentry_dsn == ""
    assert loaded.api_hash == ""
    assert loaded.bind_host == "0.0.0.0"
    assert loaded.pg_cron_enabled is False


def test_bind_host_and_pg_cron_are_configurable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The listener host and the optional database scheduler are settings."""
    loaded = _load(
        monkeypatch,
        BIND_HOST="127.0.0.1",
        PG_CRON_ENABLED="true",
    )
    assert loaded.bind_host == "127.0.0.1"
    assert loaded.pg_cron_enabled is True
    invalid = _load(monkeypatch, PG_CRON_ENABLED="maybe")
    assert invalid.pg_cron_enabled is False


def test_mtproto_session_defaults_when_blank(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A blank MTPROTO_SESSION falls back to the shared namespace."""
    assert _load(monkeypatch, MTPROTO_SESSION="  ").mtproto_session == "tcbot_mtproto"


def test_transport_env_does_not_change_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """Polling is the only transport; legacy webhook variables are ignored."""
    monkeypatch.setenv("WEBHOOK_URL", "https://bot.example.com/")
    monkeypatch.setenv("WEBHOOK_SECRET", "secret-value")
    monkeypatch.setenv("REPLIT_DEV_DOMAIN", "dev.replit.dev")
    loaded = _load(monkeypatch)
    assert not hasattr(loaded, "webhook_url")
    assert not hasattr(loaded, "webhook_secret")
