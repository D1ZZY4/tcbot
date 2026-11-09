# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Netspeed runner: Cloudflare measurement shape feeds the legacy renderer."""

from __future__ import annotations

from typing import Any

import pytest

from tcbot.modules import netspeed


def _patch_fetch(
    monkeypatch: pytest.MonkeyPatch, *, download_bytes: int = 10_000_000
) -> None:
    """Fake the HTTP layer so _run_speedtest never touches the network."""

    def _fake_fetch(
        url: str, *, data: bytes | None = None
    ) -> tuple[bytes, dict[str, str]]:
        if "cdn-cgi/trace" in url:
            return b"ip=203.0.113.7\ncolo=SIN\n", {}
        if "__down" in url:
            return b"x" * download_bytes, {}
        if "__up" in url:
            return b"ok", {}
        raise AssertionError(f"unexpected URL: {url}")

    monkeypatch.setattr(netspeed, "_get_bytes", _fake_fetch)


def test_run_speedtest_shape_feeds_renderer(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_fetch(monkeypatch)

    result = netspeed._run_speedtest()

    assert result["download"] > 0
    assert result["upload"] > 0
    assert result["ping"] >= 0
    assert result["client"]["ip"] == "203.0.113.7"
    assert result["client"]["country"] == "SIN"
    assert result["server"]["name"] == "Cloudflare"
    assert result["server"]["latency"] == result["ping"]
    assert result["share"] is None
    assert result["bytes_sent"] == 10_000_000
    assert result["bytes_received"] == 10_000_000
    assert int(result["timestamp"]) > 0


def test_run_speedtest_upload_sizes_match(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_fetch(monkeypatch, download_bytes=1000)

    result = netspeed._run_speedtest()

    assert result["bytes_received"] == 1000
    # * The upload body is always the fixed payload, independent of download.
    assert result["bytes_sent"] == 10_000_000
    assert result["client"]["isp"] == "N/A"


def test_fetch_trace_parses_key_value(monkeypatch: pytest.MonkeyPatch) -> None:
    def _trace(url: str, *, data: bytes | None = None) -> tuple[bytes, dict[str, Any]]:
        _ = data
        return b"fl=x\nip=198.51.100.9\ncolo=JKT\n", {}

    monkeypatch.setattr(netspeed, "_get_bytes", _trace)

    kv = netspeed._fetch_trace()

    assert kv == {"fl": "x", "ip": "198.51.100.9", "colo": "JKT"}
