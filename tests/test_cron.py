# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Vercel cron endpoint fail-closed security paths (see api/cron.py)."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

import api.cron as cron_mod
import tcbot.serverless as serverless_mod

# * Sentinel value; real CRON_SECRET values differ per environment, so every
# * test pins its own copy instead of trusting config.env.
_CRON_SECRET = "sentinel-cron-secret"


class _Headers:
    """Minimal stand-in for BaseHTTPRequestHandler.headers; only .get() is used."""

    def __init__(self, values: dict[str, str] | None = None) -> None:
        self._values = {key.lower(): value for key, value in (values or {}).items()}

    def get(self, name: str, default: str = "") -> str:
        """Return the header value case-insensitively, like email.message.Message."""
        return self._values.get(name.lower(), default)


def _drive(coro: Any) -> Any:
    """Drive one coroutine to completion without relying on any async plugin."""
    return asyncio.run(coro)


def _make_handler(*, authorization: str = "", reply_sink: dict[str, Any]) -> Any:
    """Build the cron handler without a live socket; stub headers and the reply sink.

    BaseHTTPRequestHandler.__init__ needs a connected socket, so the instance is
    created via object.__new__ and only the attributes do_GET touches are wired.
    """
    inst: Any = object.__new__(cron_mod.handler)
    inst.headers = _Headers({"Authorization": authorization})
    inst._reply = lambda status, body: reply_sink.update(status=status, body=body)
    return inst


def test_cron_get_503_when_secret_not_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # * cron_secret is a read-only adapter property, so swap the module's cfg
    # * reference (same pattern as test_alive_health.py) instead of patching it.
    monkeypatch.setattr(cron_mod, "cfg", SimpleNamespace(cron_secret=""))
    captured: dict[str, Any] = {}
    handler = _make_handler(reply_sink=captured)
    handler.do_GET()
    assert captured == {"status": 503, "body": "cron secret not configured"}


@pytest.mark.parametrize("authorization", ["", "Bearer not-the-secret", "Basic abc"])
def test_cron_get_401_when_bearer_missing_or_wrong(
    monkeypatch: pytest.MonkeyPatch, authorization: str
) -> None:
    monkeypatch.setattr(cron_mod, "cfg", SimpleNamespace(cron_secret=_CRON_SECRET))
    captured: dict[str, Any] = {}
    handler = _make_handler(authorization=authorization, reply_sink=captured)
    handler.do_GET()
    assert captured == {"status": 401, "body": "Unauthorized"}


def test_cron_get_delegates_to_run_warn_expiry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cron_mod, "cfg", SimpleNamespace(cron_secret=_CRON_SECRET))

    async def _fake_expiry() -> tuple[int, str]:
        return 200, "warn expiry ran (older than 30d pruned)"

    monkeypatch.setattr(cron_mod, "run_warn_expiry", _fake_expiry)
    monkeypatch.setattr(cron_mod, "run", _drive)
    captured: dict[str, Any] = {}
    handler = _make_handler(authorization=f"Bearer {_CRON_SECRET}", reply_sink=captured)
    handler.do_GET()
    assert captured == {
        "status": 200,
        "body": "warn expiry ran (older than 30d pruned)",
    }


def test_cron_get_200_when_warn_expiry_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cron_mod, "cfg", SimpleNamespace(cron_secret=_CRON_SECRET))
    # * The real run_warn_expiry only reads serverless.cfg.warn_expiry_days and
    # * returns before any database access when expiry is disabled.
    monkeypatch.setattr(serverless_mod, "cfg", SimpleNamespace(warn_expiry_days=0))
    monkeypatch.setattr(cron_mod, "run", _drive)
    captured: dict[str, Any] = {}
    handler = _make_handler(authorization=f"Bearer {_CRON_SECRET}", reply_sink=captured)
    handler.do_GET()
    assert captured == {
        "status": 200,
        "body": "warn expiry disabled (WARN_EXPIRY_DAYS=0)",
    }
