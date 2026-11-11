# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Netspeed runner: speedtest.net selection shape feeds the legacy renderer."""

from __future__ import annotations

import threading

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
        url: str,
        *,
        data: bytes | None = None,
        timeout: float | None = None,
        cancel: threading.Event | None = None,
    ) -> tuple[bytes, dict[str, str]]:
        _ = timeout
        _ = cancel
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
    def _fake(
        url: str,
        *,
        data: bytes | None = None,
        timeout: float | None = None,
        cancel: threading.Event | None = None,
    ) -> tuple[bytes, dict[str, str]]:
        _ = data
        _ = timeout
        _ = cancel
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


def test_the_run_keeps_the_host_link_cheap() -> None:
    """The measurement must not saturate the host the bot runs on.

    The bot and the speed test share one CPU and one network link, so a
    large saturating transfer starves the event loop of CPU and delays
    every Telegram API call. The payload has to stay small.
    """
    download_bytes = sum(netspeed._DOWNLOAD_SIZES) * 1024 * netspeed._DOWNLOAD_THREADS
    upload_bytes = sum(netspeed._UPLOAD_SIZES) * netspeed._UPLOAD_THREADS
    total_mb = (download_bytes + upload_bytes) / (1024 * 1024)
    assert total_mb <= 3.0, f"speed test moves {total_mb:.1f} MB on the bot host"
    # * Each direction must stay on a small connection count so the link
    # * keeps room for the bot's own traffic.
    assert netspeed._DOWNLOAD_THREADS <= 2
    assert netspeed._UPLOAD_THREADS <= 2


def test_a_second_run_is_refused_instead_of_queued() -> None:
    """Only one run may own the host at a time."""
    assert netspeed._run_lock.acquire(blocking=False)
    try:
        assert not netspeed._run_lock.acquire(blocking=False)
    finally:
        netspeed._run_lock.release()


def test_a_cancelled_run_stops_at_the_next_request() -> None:
    """The cancel flag must release the host instead of running to the end."""
    cancel = threading.Event()
    cancel.set()

    def _fake(
        url: str,
        *,
        data: bytes | None = None,
        timeout: float | None = None,
        cancel: threading.Event | None = None,
    ) -> tuple[bytes, dict[str, str]]:
        raise AssertionError(f"request issued after cancel: {url}")

    monkey = pytest.MonkeyPatch()
    monkey.setattr(netspeed, "_get_bytes", _fake)
    try:
        with pytest.raises(netspeed._SpeedtestCancelled):
            netspeed._run_speedtest(cancel)
    finally:
        monkey.undo()


def test_the_run_does_not_use_the_event_loop_default_executor() -> None:
    """The dedicated worker keeps the shared default executor free."""
    assert netspeed._speedtest_executor() is netspeed._speedtest_executor()
    assert netspeed._speedtest_executor() is not None
