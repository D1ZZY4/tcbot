# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Runtime configuration parsing and the primary-group contract."""

from __future__ import annotations

import dataclasses

import pytest

from tcbot import Configs, cfg, parse_chat_id, parse_list, parse_port


def _load(monkeypatch: pytest.MonkeyPatch, **env: str) -> Configs:
    """Load a fresh Configs with *env* applied over the required defaults."""
    base: dict[str, str] = {
        "BOT_TOKEN": "000000:dummy-token-for-lint000000000000000",
        "DATABASE_URL": "postgresql://localhost:5432/tcbot",
        "OWNER_ID": "1",
    }
    base.update(env)
    for key in (
        "DATABASE_SCHEMA_MODE",
        "FEDERATION_SLUG",
        "MAIN_GROUP",
        "LOGS",
        "LOGS_ERRORS",
        "APPEALS",
        "PROOFS",
        "PORT",
        "PREFIXES",
        "WEBHOOK_URL",
        "WEBHOOK_SECRET",
        "CRON_SECRET",
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


def test_invalid_chat_id_falls_back_to_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A malformed destination resolves to the unset sentinel, not a crash."""
    loaded = _load(monkeypatch, LOGS="not-a-chat")
    assert loaded.logs == (0, None)


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
    assert cfg.is_webhook_mode == bool(cfg.webhook_url)
    assert cfg.mtproto_enabled == (cfg.api_id > 0 and bool(cfg.api_hash))


def test_parse_helpers_keep_their_contract() -> None:
    """The exported parsing helpers keep their documented behaviour."""
    assert parse_list("") == []
    assert parse_list("['a', 'b']") == ["a", "b"]
    assert parse_list("a, b") == ["a", "b"]
    assert parse_port("") == 5000
    assert parse_chat_id("") == (0, None)


def test_env_fallbacks_use_documented_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Blank optional variables fall back to their documented defaults."""
    loaded = _load(monkeypatch, COMMUNITY_NAME="  ")
    assert loaded.community_name == "Bot"
    assert loaded.community_channel_url == "https://t.me/TranssionCoreFederation"


def test_optional_secrets_stay_empty_when_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unset optional credentials stay empty instead of becoming truthy."""
    loaded = _load(monkeypatch)
    assert loaded.redis_url is None
    assert loaded.cron_secret == ""
    assert loaded.sentry_dsn == ""
    assert loaded.api_hash == ""


def test_explicit_webhook_secret_is_kept_separately(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The serverless receiver compares against the explicit secret only."""
    loaded = _load(monkeypatch, WEBHOOK_SECRET="s3cret")
    assert loaded.webhook_secret == "s3cret"
    assert loaded.webhook_secret_explicit == "s3cret"
    generated = _load(monkeypatch)
    assert generated.webhook_secret_explicit == ""
    assert generated.webhook_secret


def test_mtproto_session_defaults_when_blank(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A blank MTPROTO_SESSION falls back to the shared namespace."""
    assert _load(monkeypatch, MTPROTO_SESSION="  ").mtproto_session == "tcbot_mtproto"


def test_unknown_log_level_falls_back_to_info(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unusable LOG_LEVEL never silences the bot entirely."""
    loaded = _load(monkeypatch, LOG_LEVEL="LOUD")
    assert loaded.log_level == 20



def test_database_schema_mode_defaults_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Existing deployments keep their Alembic-managed legacy schema by default."""
    loaded = _load(monkeypatch)
    assert loaded.database_schema_mode == "legacy"
    assert loaded.federation_slug == "tcf"


def test_normalized_schema_mode_uses_the_configured_federation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The normalized runtime is explicit and scopes queries by federation slug."""
    loaded = _load(
        monkeypatch,
        DATABASE_SCHEMA_MODE="normalized",
        FEDERATION_SLUG="transsion-core",
    )
    assert loaded.database_schema_mode == "normalized"
    assert loaded.federation_slug == "transsion-core"


def test_unknown_database_schema_mode_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A typo must not silently choose a migration path."""
    with pytest.raises(
        RuntimeError,
        match="DATABASE_SCHEMA_MODE must be either 'legacy' or 'normalized'",
    ):
        _load(monkeypatch, DATABASE_SCHEMA_MODE="normalised")
