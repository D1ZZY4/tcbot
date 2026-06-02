# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""Tests for the keep-alive Flask server (alive.py)."""

from __future__ import annotations

import threading

from tcbot import alive

# ────────────────────────── Flask endpoint ──────────────────────── #


def test_health_endpoint_returns_ok() -> None:
    """GET / returns exactly the string "OK" with HTTP 200."""
    client = alive._app.test_client()
    response = client.get("/")
    assert response.status_code == 200
    assert response.data == b"OK"


def test_health_endpoint_post_method_not_allowed() -> None:
    """POST / is not registered and should return 405."""
    client = alive._app.test_client()
    response = client.post("/")
    assert response.status_code == 405


def test_health_endpoint_unknown_path_is_404() -> None:
    """Unregistered paths return 404."""
    client = alive._app.test_client()
    response = client.get("/healthz")
    assert response.status_code == 404


# ──────────────────────── Thread launch ─────────────────────────── #


def test_start_keepalive_spawns_daemon_thread(monkeypatch) -> None:
    """start_keepalive() starts a daemon thread named 'keepalive'."""
    spawned: list[threading.Thread] = []

    def _capture_start(self, *args, **kwargs):
        spawned.append(self)

    monkeypatch.setattr(threading.Thread, "start", _capture_start)
    monkeypatch.setattr(alive, "_run", lambda: None)

    alive.start_keepalive()

    assert len(spawned) == 1
    t = spawned[0]
    assert t.name == "keepalive"
    assert t.daemon is True


def test_start_keepalive_logs_port(monkeypatch, caplog) -> None:
    """start_keepalive() emits an INFO log containing the port number."""
    import logging

    monkeypatch.setattr(threading.Thread, "start", lambda self: None)
    monkeypatch.setattr(alive, "_run", lambda: None)

    with caplog.at_level(logging.INFO, logger="tcbot.alive"):
        alive.start_keepalive()

    assert any(str(alive.cfg.port) in record.message for record in caplog.records)
