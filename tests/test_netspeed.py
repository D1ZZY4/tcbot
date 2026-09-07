# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Ookla share-URL gate: http(s) images pass, anything else falls back to text."""

from __future__ import annotations

from tcbot.modules.netspeed import _share_photo_url


def test_ookla_http_share_accepted() -> None:
    assert (
        _share_photo_url({"share": "http://www.speedtest.net/result/12345.png"})
        == "http://www.speedtest.net/result/12345.png"
    )


def test_https_share_accepted() -> None:
    assert (
        _share_photo_url({"share": "https://www.speedtest.net/result/12345.png"})
        == "https://www.speedtest.net/result/12345.png"
    )


def test_non_http_share_rejected() -> None:
    assert _share_photo_url({"share": "ftp://example.com/x.png"}) is None
    assert _share_photo_url({"share": "javascript:alert(1)"}) is None
    assert _share_photo_url({"share": ""}) is None
    assert _share_photo_url({}) is None
    assert _share_photo_url({"share": None}) is None
    assert _share_photo_url({"share": 12345}) is None
