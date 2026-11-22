# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Error reports use a rich collapsible detail list with MarkdownV2 fallback."""

from __future__ import annotations

import asyncio
from typing import Any

from tcbot import cfg, error_reporter


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
        async def do_api_request(
            self, endpoint: str, *, api_kwargs: Any, return_type: Any
        ) -> str:
            calls.append({"endpoint": endpoint, **api_kwargs})
            return "sent"

        async def send_message(self, *_args: Any, **_kwargs: Any) -> str:
            return "fallback"

    monkeypatch.setattr(error_reporter, "_bot", _Bot())
    monkeypatch.setattr(error_reporter, "_chat_id", -100)
    monkeypatch.setattr(error_reporter, "_thread_id", None)

    asyncio.run(error_reporter.send_to_log_errors("plain", {"html": "<p>x</p>"}))

    assert calls
    assert calls[0]["endpoint"] == "sendRichMessage"
    assert calls[0]["rich_message"] == {"html": "<p>x</p>"}
