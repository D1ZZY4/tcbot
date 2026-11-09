# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Netspeed runner: speedtest.net selection shape feeds the legacy renderer."""

from __future__ import annotations

import pytest

from tcbot.modules import netspeed

_CONFIG_XML = (
    b'<?xml version="1.0" encoding="UTF-8"?><settings>'
    b'<client ip="203.0.113.7" lat="-7.25" lon="112.75" '
    b'isp="Test ISP" isprating="3.7" country="ID" />'
    b'<server-config threadcount="4" ignoreids="99999" />'
    b"</settings>"
)

_SERVERS_XML = (
    b'<?xml version="1.0" encoding="UTF-8"?><settings><servers>'
    b'<server url="http://far.example:8080/speedtest/upload.php" lat="0.0" '
    b'lon="0.0" name="Far" country="Farland" cc="FR" sponsor="FarSponsor" '
    b'id="11111" host="far.example:8080" />'
    b'<server url="http://near.example:8080/speedtest/upload.php" lat="-7.24" '
    b'lon="112.74" name="Near" country="Indonesia" cc="ID" '
    b'sponsor="NearSponsor" id="22222" host="near.example:8080" />'
    b'<server url="http://ignored.example:8080/speedtest/upload.php" lat="-7.24" '
    b'lon="112.74" name="Ignored" country="Indonesia" cc="ID" '
    b'sponsor="Ignored" id="99999" host="ignored.example:8080" />'
    b"</servers></settings>"
)


def _patch_fetch(
    monkeypatch: pytest.MonkeyPatch, *, download_bytes: int = 1000
) -> None:
    """Fake the HTTP layer so _run_speedtest never touches the network."""

    def _fake_fetch(
        url: str, *, data: bytes | None = None
    ) -> tuple[bytes, dict[str, str]]:
        if "speedtest-config.php" in url:
            return _CONFIG_XML, {}
        if "speedtest-servers-static.php" in url:
            return _SERVERS_XML, {}
        if "latency.txt" in url:
            # * Only the near server answers; far stays unreachable so the
            # * best-server pick is deterministic under the instant mock.
            if "far.example" in url:
                raise RuntimeError("unreachable")
            return b"test=test\n", {}
        if "random" in url and ".jpg" in url:
            return b"x" * download_bytes, {}
        if "upload.php" in url:
            assert data is not None
            return f"size={len(data)}".encode(), {}
        raise AssertionError(f"unexpected URL: {url}")

    monkeypatch.setattr(netspeed, "_get_bytes", _fake_fetch)


def test_run_speedtest_shape_feeds_renderer(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_fetch(monkeypatch)

    result = netspeed._run_speedtest()

    downloads = len(netspeed._DOWNLOAD_SIZES) * netspeed._DOWNLOAD_THREADS
    uploads = sum(netspeed._UPLOAD_SIZES) * netspeed._UPLOAD_THREADS
    assert result["download"] > 0
    assert result["upload"] > 0
    assert result["ping"] >= 0
    assert result["client"]["ip"] == "203.0.113.7"
    assert result["client"]["isp"] == "Test ISP"
    assert result["client"]["country"] == "ID"
    assert result["server"]["name"] == "Near"
    assert result["server"]["sponsor"] == "NearSponsor"
    assert result["server"]["latency"] == result["ping"]
    assert result["share"] is None
    assert result["bytes_sent"] == uploads
    assert result["bytes_received"] == downloads * 1000
    assert int(result["timestamp"]) > 0


def test_run_speedtest_upload_independent_of_download(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_fetch(monkeypatch, download_bytes=500)

    result = netspeed._run_speedtest()

    downloads = len(netspeed._DOWNLOAD_SIZES) * netspeed._DOWNLOAD_THREADS
    uploads = sum(netspeed._UPLOAD_SIZES) * netspeed._UPLOAD_THREADS
    assert result["bytes_received"] == downloads * 500
    # * The upload total is always the fixed size subset, independent of
    # * the mocked download payload.
    assert result["bytes_sent"] == uploads


def test_distance_orders_closest_first() -> None:
    origin = (-7.25, 112.75)
    near = netspeed._distance_km(origin, (-7.24, 112.74))
    far = netspeed._distance_km(origin, (0.0, 0.0))
    assert near < far


def test_fetch_config_ignores_bad_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake(url: str, *, data: bytes | None = None) -> tuple[bytes, dict[str, str]]:
        _ = data
        return (
            b'<?xml version="1.0"?><settings>'
            b'<client ip="1.2.3.4" lat="0" lon="0" />'
            b'<server-config threadcount="2" ignoreids="bad, 7, ,8" />'
            b"</settings>",
            {},
        )

    monkeypatch.setattr(netspeed, "_get_bytes", _fake)

    client, ignore, threads = netspeed._fetch_config()

    assert client["ip"] == "1.2.3.4"
    assert ignore == {7, 8}
    assert threads == 2
