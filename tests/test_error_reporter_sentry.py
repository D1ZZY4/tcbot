# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Sentry events are redacted with the same contract as Telegram reports."""

from __future__ import annotations

from tcbot import cfg, error_reporter


def test_sentry_event_strings_are_redacted_recursively() -> None:
    event = {
        "level": "error",
        "message": {"formatted": f"failed with {cfg.bot_token}"},
        "exception": {"values": [{"value": f"dsn {cfg.sentry_dsn}"}]},
        "breadcrumbs": {"values": [{"message": f"url {cfg.database_url}"}]},
        "extra": {"attempt": 3},
    }

    scrubbed = error_reporter.scrub_sentry_event(event, None)

    assert scrubbed["level"] == "error"
    assert scrubbed["extra"] == {"attempt": 3}
    assert cfg.bot_token not in scrubbed["message"]["formatted"]
    assert cfg.database_url not in scrubbed["breadcrumbs"]["values"][0]["message"]
    if cfg.sentry_dsn:
        assert cfg.sentry_dsn not in scrubbed["exception"]["values"][0]["value"]


def test_sentry_scrubber_replaces_credential_shaped_patterns() -> None:
    event = {
        "message": {
            "formatted": "token 123456:AAABBBCCCDDDEEEFFFGGGHHHIIIJJJKKK and "
            "postgres://user:pass@host/db"
        }
    }

    scrubbed = error_reporter.scrub_sentry_event(event, None)

    text = scrubbed["message"]["formatted"]
    assert "AAABBBCCCDDDEEEFFFGGGHHHIIIJJJKKK" not in text
    assert "user:pass" not in text
