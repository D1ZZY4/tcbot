# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Error reports use a rich collapsible detail list on both delivery paths."""

from __future__ import annotations

import asyncio
from typing import Any

from tcbot import cfg
from tcbot.modules.helper.pipelines.errors import report as error_reporter


def _report(exc: BaseException, context: str | None = None) -> dict[str, Any]:
    return error_reporter.build_error_report_payload(exc=exc, context=context)


def test_payload_uses_a_collapsible_details_list() -> None:
    try:
        raise ValueError("boom")
    except ValueError as exc:
        payload = _report(exc, context="extra")

    html = payload["html"]
    assert "<h2>Error Report</h2>" in html
    assert "<details>" in html
    assert "<summary><b>Details</b></summary>" in html
    assert "<ul>" in html
    assert "Traceback:" in html
    assert "Context:" in html
    # * A rich payload never sets more than one content field.
    assert set(payload) == {"html"}


def test_payload_scrubs_secrets() -> None:
    payload = _report(ValueError(f"token {cfg.bot_token}"), context=cfg.database_url)

    html = payload["html"]
    assert cfg.bot_token not in html
    assert cfg.database_url not in html


def test_delivery_sends_rich_with_markdown_fallback(monkeypatch: Any) -> None:
    calls: list[dict[str, Any]] = []

    class _Bot:
        async def send_rich_message(
            self, chat_id: Any, rich_message: Any, **_kwargs: Any
        ) -> str:
            calls.append(
                {
                    "endpoint": "sendRichMessage",
                    "chat_id": chat_id,
                    "rich_message": {"html": rich_message.html},
                }
            )
            return "sent"

    monkeypatch.setattr(error_reporter, "_bot", _Bot())
    monkeypatch.setattr(error_reporter, "_chat_id", -100)
    monkeypatch.setattr(error_reporter, "_thread_id", None)

    asyncio.run(error_reporter.send_to_log_errors({"html": "<p>x</p>"}))

    assert calls
    assert calls[0]["endpoint"] == "sendRichMessage"
    assert calls[0]["rich_message"] == {"html": "<p>x</p>"}


def test_owner_dm_uses_the_rich_payload(monkeypatch: Any) -> None:
    calls: list[dict[str, Any]] = []

    class _Bot:
        async def send_rich_message(
            self, chat_id: Any, rich_message: Any, **_kwargs: Any
        ) -> str:
            calls.append(
                {
                    "endpoint": "sendRichMessage",
                    "chat_id": chat_id,
                    "rich_message": {"html": rich_message.html},
                }
            )
            return "sent"

    monkeypatch.setattr(error_reporter, "_bot", _Bot())
    monkeypatch.setattr(error_reporter, "_owner_id", 123)

    asyncio.run(error_reporter.send_to_owner({"html": "<p>owner</p>"}))

    assert calls == [
        {
            "endpoint": "sendRichMessage",
            "chat_id": 123,
            "rich_message": {"html": "<p>owner</p>"},
        }
    ]


def test_a_failed_owner_dm_falls_back_to_the_log_channel(monkeypatch: Any) -> None:
    calls: list[dict[str, Any]] = []

    class _Bot:
        async def send_rich_message(
            self, chat_id: Any, rich_message: Any, **_kwargs: Any
        ) -> str:
            if chat_id == 123:
                raise RuntimeError("owner unreachable")
            return "sent"

    async def _log(payload: dict[str, Any]) -> None:
        calls.append(payload)

    monkeypatch.setattr(error_reporter, "_bot", _Bot())
    monkeypatch.setattr(error_reporter, "_owner_id", 123)
    monkeypatch.setattr(error_reporter, "_chat_id", -100)
    monkeypatch.setattr(error_reporter, "_thread_id", None)
    monkeypatch.setattr(error_reporter, "send_to_log_errors", _log)

    asyncio.run(error_reporter.send_to_owner({"html": "<p>owner</p>"}))

    assert calls == [{"html": "<p>owner</p>"}]


def test_no_owner_fallback_when_the_log_channel_is_the_owner(monkeypatch: Any) -> None:
    calls: list[dict[str, Any]] = []

    class _Bot:
        async def send_rich_message(
            self, chat_id: Any, rich_message: Any, **_kwargs: Any
        ) -> str:
            raise RuntimeError("owner unreachable")

    async def _log(payload: dict[str, Any]) -> None:
        calls.append(payload)

    monkeypatch.setattr(error_reporter, "_bot", _Bot())
    monkeypatch.setattr(error_reporter, "_owner_id", 123)
    monkeypatch.setattr(error_reporter, "_chat_id", 123)
    monkeypatch.setattr(error_reporter, "_thread_id", None)
    monkeypatch.setattr(error_reporter, "send_to_log_errors", _log)

    asyncio.run(error_reporter.send_to_owner({"html": "<p>owner</p>"}))

    assert calls == []
